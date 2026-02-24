import argparse
import json
import os
import socket
import sqlite3
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "gateway.db")
LOG_PATH = os.path.join(BASE_DIR, "logs", "gateway.log")
NODES_PATH = os.path.join(BASE_DIR, "nodes.json")

HOST = "0.0.0.0"
PORT = 8080


def log(msg: str):
    ts = datetime.utcnow().isoformat()
    line = f"{ts} | {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


def db():
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.execute("PRAGMA journal_mode=WAL;")
    return con


def load_nodes():
    with open(NODES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def insert_dynamic(table: str, columns: list[str], values: list[float]):
    if len(columns) != len(values):
        raise ValueError("columns/values length mismatch")

    con = db()
    try:
        cols_sql = ", ".join(columns)
        qs = ", ".join(["?"] * len(values))
        
        ts_utc = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        
        con.execute(
            f"INSERT INTO {table} (ts_utc, {cols_sql}, sent) VALUES (?, {qs}, 0)",
            (ts_utc, *values),
        )
        con.commit()
    finally:
        con.close()


# -------------------------
# Parsing / routing
# -------------------------

def parse_kv_legacy(line: str):
    """node=<id>,temp=...,hum=...,pres=..."""
    parts = [p.strip() for p in line.split(",") if p and p.strip()]
    kv = {}
    for p in parts:
        if "=" not in p:
            continue
        k, v = p.split("=", 1)
        kv[k.strip().lower()] = v.strip()

    node_id = kv.get("node")
    temp = kv.get("temp")
    hum = kv.get("hum")
    pres = kv.get("pres")

    if node_id is None or temp is None or hum is None or pres is None:
        raise ValueError("Faltan campos (node/temp/hum/pres)")

    return node_id, {"temperature": float(temp), "humidity": float(hum), "pressure": float(pres)}


def route_and_parse(line: str):
    """
    Routing por prefijo (según tu decisión):
      - Teide02:  "TEST,hum,temp"
      - Cueva_Teide: "DATA,incliX,incliY,temp"

    Compatibilidad extra:
      - Legacy: "node=teide01,temp=...,hum=...,pres=..."

    Devuelve: (node_id, dict{col: value})
    """
    line = line.strip()
    if not line:
        raise ValueError("Línea vacía")

    # Teide02
    if line.startswith("TEST,"):
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 3:
            raise ValueError("TEST requiere 2 valores: TEST,hum,temp")
        hum = float(parts[1])
        temp = float(parts[2])
        return "teide02", {"humidity": hum, "temperature": temp}

    # Cueva_Teide
    if line.startswith("DATA,"):
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 4:
            raise ValueError("DATA requiere 3 valores: DATA,incliX,incliY,temp")
        incli_x = float(parts[1])
        incli_y = float(parts[2])
        temp = float(parts[3])
        return "Cueva_Teide", {"incli_x": incli_x, "incli_y": incli_y, "temperature": temp}

    # Legacy kv
    if "node=" in line.lower():
        return parse_kv_legacy(line)

    raise ValueError("Formato no reconocido")


# -------------------------
# Inputs: TCP / Serial
# -------------------------

def process_line(line: str, nodes_cfg: dict):
    node_id, values_dict = route_and_parse(line)

    if node_id not in nodes_cfg:
        raise ValueError(f"Nodo '{node_id}' no existe en nodes.json")

    table = nodes_cfg[node_id]["table"]
    cols = nodes_cfg[node_id]["db_columns"]

    # Ensure all needed columns exist in parsed dict
    values = []
    for c in cols:
        if c not in values_dict:
            raise ValueError(f"Falta columna '{c}' para nodo {node_id}")
        values.append(values_dict[c])

    insert_dynamic(table, cols, values)
    log(f"RX OK: node={node_id} values={values_dict} raw='{line.strip()}'")


def run_tcp(nodes_cfg: dict, host: str, port: int):
    log(f"Receiver TCP iniciado en {host}:{port}")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((host, port))
        s.listen(5)

        while True:
            conn, addr = s.accept()
            log(f"Conexión entrante: {addr}")
            with conn:
                buf = ""
                while True:
                    data = conn.recv(1024)
                    if not data:
                        break
                    buf += data.decode("utf-8", errors="ignore")

                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            process_line(line, nodes_cfg)
                            conn.sendall(b"OK\n")
                        except Exception as e:
                            log(f"RX ERROR: '{line}' -> {e}")
                            conn.sendall(b"ERR\n")

            log(f"Conexión cerrada: {addr}")


def run_serial(nodes_cfg: dict, port: str, baud: int):
    try:
        import serial  # pyserial
    except Exception:
        raise RuntimeError("Falta pyserial: pip3 install pyserial")

    log(f"Receiver SERIAL iniciado en {port} @ {baud}")

    with serial.Serial(port, baudrate=baud, timeout=1) as ser:
        while True:
            raw = ser.readline()
            if not raw:
                continue
            try:
                line = raw.decode("utf-8", errors="ignore").strip()
                if not line:
                    continue
                process_line(line, nodes_cfg)
            except Exception as e:
                log(f"RX ERROR (SER): '{raw}' -> {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["tcp", "serial"], default="tcp")
    ap.add_argument("--host", default=HOST)
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--serial-port", default="/dev/serial0")
    ap.add_argument("--baud", type=int, default=9600)
    args = ap.parse_args()

    nodes_cfg = load_nodes()

    if args.mode == "tcp":
        run_tcp(nodes_cfg, args.host, args.port)
    else:
        run_serial(nodes_cfg, args.serial_port, args.baud)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"Receiver FATAL: {e}")
        raise
