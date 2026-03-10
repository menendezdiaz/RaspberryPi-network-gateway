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

def parse_kv_line(line: str):
    parts = [p.strip() for p in line.split(",") if p and p.strip()]
    kv = {}
    for p in parts:
        if "=" not in p:
            continue
        k, v = p.split("=", 1)
        kv[k.strip()] = v.strip()
    return kv



def parse_by_node_config(line: str, node_id: str, node_cfg: dict):
    input_cfg = node_cfg.get("input", {})
    fmt = input_cfg.get("format")
    match_cfg = input_cfg.get("match", {})

    # -------------------------
    # KV format
    # Ejemplo: node=teide01,temp=23,hum=50,pres=900
    # -------------------------
    if fmt == "kv":
        contains = match_cfg.get("contains")
        node_key = match_cfg.get("node_key")
        node_value = match_cfg.get("node_value")

        if contains and contains not in line:
            return None

        kv = parse_kv_line(line)

        if node_key and kv.get(node_key) != node_value:
            return None

        field_map = input_cfg.get("field_map", {})
        values_dict = {}

        for raw_key, db_col in field_map.items():
            if raw_key not in kv:
                raise ValueError(f"Falta campo '{raw_key}' en mensaje KV de {node_id}")
            values_dict[db_col] = float(kv[raw_key])

        return node_id, values_dict

    # -------------------------
    # CSV format
    # Ejemplo: TEST,hum,temp  o  DATA,x,y,temp
    # -------------------------
    if fmt == "csv":
        prefix = match_cfg.get("prefix")
        if prefix and not line.startswith(prefix):
            return None

        parts = [p.strip() for p in line.split(",")]
        csv_cfg = input_cfg.get("csv", {})
        expected_len = csv_cfg.get("expected_len")
        field_positions = csv_cfg.get("fields", {})

        if expected_len is not None and len(parts) != expected_len:
            raise ValueError(
                f"{node_id}: se esperaban {expected_len} elementos y llegaron {len(parts)}"
            )

        values_dict = {}
        for pos_str, db_col in field_positions.items():
            pos = int(pos_str)
            if pos >= len(parts):
                raise ValueError(f"{node_id}: posición {pos} fuera de rango")
            values_dict[db_col] = float(parts[pos])

        return node_id, values_dict

    raise ValueError(f"Nodo '{node_id}' con formato no soportado: {fmt}")



def route_and_parse(line: str, nodes_cfg: dict):
    line = line.strip()
    if not line:
        raise ValueError("Línea vacía")

    parse_errors = []

    for node_id, node_cfg in nodes_cfg.items():
        try:
            result = parse_by_node_config(line, node_id, node_cfg)
            if result is not None:
                return result
        except Exception as e:
            parse_errors.append(f"{node_id}: {e}")

    if parse_errors:
        raise ValueError(
            "La línea no pudo parsearse con ningún nodo. "
            + "Errores: " + " | ".join(parse_errors)
        )

    raise ValueError("Formato no reconocido por ningún nodo configurado")










# -------------------------
# Inputs: TCP / Serial
# -------------------------


def process_line(line: str, nodes_cfg: dict):
    node_id, values_dict = route_and_parse(line, nodes_cfg)

    if node_id not in nodes_cfg:
        raise ValueError(f"Nodo '{node_id}' no existe en nodes.json")

    table = nodes_cfg[node_id]["table"]
    cols = nodes_cfg[node_id]["db_columns"]

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
