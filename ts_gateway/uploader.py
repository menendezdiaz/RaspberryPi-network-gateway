import json
import time
import sqlite3
import os
from datetime import datetime
import requests

# =========================
# CONFIG
# =========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "gateway.db")
LOG_PATH = os.path.join(BASE_DIR, "logs", "gateway.log")
NODES_PATH = os.path.join(BASE_DIR, "nodes.json")

THINGSPEAK_URL = "https://api.thingspeak.com/update"

INTERVAL = 5
MAX_BACKLOG_PER_CYCLE = 15
THINGSPEAK_MIN_DELAY = 16

# =========================
# Utils
# =========================

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

def fetch_pending(table: str, columns: list[str], limit: int):
    con = db()
    try:
        col_sql = ", ".join(columns)
        cur = con.execute(
            f"SELECT id, ts_utc, {col_sql} FROM {table} WHERE sent=0 ORDER BY id ASC LIMIT ?",
            (limit,),
        )
        return cur.fetchall()
    finally:
        con.close()

def mark_sent(table: str, row_id: int):
    con = db()
    try:
        con.execute(f"UPDATE {table} SET sent=1 WHERE id=?", (row_id,))
        con.commit()
    finally:
        con.close()

def send_to_thingspeak(payload: dict, write_key: str) -> bool:
    params = {"api_key": write_key}
    params.update(payload)

    try:
        r = requests.get(THINGSPEAK_URL, params=params, timeout=10)
        return r.status_code == 200 and r.text.strip().isdigit()
    except requests.RequestException as e:
        log(f"Sin internet / error HTTP: {e}")
        return False

# =========================
# Main loop
# =========================
log("Uploader iniciado (SQLite -> ThingSpeak)")

while True:
    try:
        nodes = load_nodes()

        for node_id, cfg in nodes.items():
            table = cfg["table"]
            cols = cfg["db_columns"]
            ts_cfg = cfg.get("thingspeak", {})
            write_key = ts_cfg.get("write_key")
            field_map = ts_cfg.get("fields", {})

            if not write_key:
                log(f"{node_id}--> Sin write_key en nodes.json (salto)")
                continue

            pending = fetch_pending(table, cols, MAX_BACKLOG_PER_CYCLE)
            if pending:
                log(f"{node_id}--> Pendientes a intentar: {len(pending)}")

            for row in pending:
                row_id = row[0]
                ts_utc = row[1]
                values = row[2:]

                # Build payload: fieldN -> value (según mapping)
                payload = {"created_at": ts_utc}            # para que Thingspeak ponga esa hora
                
                for field_name, col_name in field_map.items():
                    if col_name in cols:
                        payload[field_name] = values[cols.index(col_name)]

                ok = send_to_thingspeak(payload, write_key)

                if ok:
                    mark_sent(table, row_id)
                    log(f"{node_id}--> Subido OK id={row_id} payload={payload}")
                    time.sleep(THINGSPEAK_MIN_DELAY)
                else:
                    log(f"{node_id}--> No se pudo subir (queda pendiente). Corto ciclo.")
                    break

            time.sleep(INTERVAL)

    except Exception as e:
        log(f"ERROR inesperado (no paro el programa): {e}")
        time.sleep(50)
