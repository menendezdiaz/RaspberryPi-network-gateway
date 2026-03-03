import json
import time
import sqlite3
import os
from datetime import datetime, timedelta, timezone
import requests

# =========================
# CONFIG
# =========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "gateway.db")
LOG_PATH = os.path.join(BASE_DIR, "logs", "gateway.log")
NODES_PATH = os.path.join(BASE_DIR, "nodes.json")

THINGSPEAK_URL = "https://api.thingspeak.com/update"

# Cada cuánto se despierta el uploader para mirar si hay trabajo
INTERVAL = 5

# Ventana de promedio y “ritmo” objetivo de subida
UPLOAD_PERIOD_SEC = 10 * 60  # 10 minutos

# Para “ponerse al día” si hay backlog grande: cuántas ventanas sube por ciclo
MAX_WINDOWS_PER_CYCLE = 6

# Respeta el límite típico de ThingSpeak (>= 15s)
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

def parse_ts_utc(ts: str) -> datetime:
    """
    Admite ISO (ej: '2026-03-03T12:34:56.123456' o con 'Z').
    Asume UTC si no trae tzinfo.
    """
    ts = ts.strip()
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")

def get_oldest_pending_ts(table: str) -> str | None:
    con = db()
    try:
        cur = con.execute(f"SELECT ts_utc FROM {table} WHERE sent=0 ORDER BY ts_utc ASC LIMIT 1")
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        con.close()

def fetch_pending_window(table: str, columns: list[str], start_ts: str, end_ts: str):
    """
    Trae filas pendientes en [start_ts, end_ts)
    """
    con = db()
    try:
        col_sql = ", ".join(columns)
        cur = con.execute(
            f"""
            SELECT id, ts_utc, {col_sql}
            FROM {table}
            WHERE sent=0 AND ts_utc >= ? AND ts_utc < ?
            ORDER BY ts_utc ASC
            """,
            (start_ts, end_ts),
        )
        return cur.fetchall()
    finally:
        con.close()

def mark_sent_window(table: str, start_ts: str, end_ts: str) -> int:
    con = db()
    try:
        cur = con.execute(
            f"UPDATE {table} SET sent=1 WHERE sent=0 AND ts_utc >= ? AND ts_utc < ?",
            (start_ts, end_ts),
        )
        con.commit()
        return cur.rowcount
    finally:
        con.close()

def safe_float(x):
    if x is None:
        return None
    try:
        return float(x)
    except (ValueError, TypeError):
        return None

def average_columns(rows_values: list[tuple], n_cols: int) -> list[float | None]:
    """
    rows_values: lista de tuplas con valores (solo columnas, sin id/ts)
    devuelve promedio por columna (None si no hay valores numéricos)
    """
    avgs = []
    for j in range(n_cols):
        vals = []
        for rv in rows_values:
            v = safe_float(rv[j])
            if v is not None:
                vals.append(v)
        avgs.append(sum(vals) / len(vals) if vals else None)
    return avgs

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
                continue

            windows_sent = 0

            while windows_sent < MAX_WINDOWS_PER_CYCLE:
                oldest_ts = get_oldest_pending_ts(table)
                if not oldest_ts:
                    break

                start_dt = parse_ts_utc(oldest_ts)
                end_dt = start_dt + timedelta(seconds=UPLOAD_PERIOD_SEC)
                now_dt = datetime.now(timezone.utc)

                # Si la ventana no está completa → no hacemos nada y salimos
                if now_dt < end_dt:
                    break

                start_ts = iso_utc(start_dt)
                end_ts = iso_utc(end_dt)

                pending = fetch_pending_window(table, cols, start_ts, end_ts)
                if not pending:
                    break

                values_only = [row[2:] for row in pending]
                avgs = average_columns(values_only, len(cols))

                payload = {"created_at": end_ts}

                for field_name, col_name in field_map.items():
                    if col_name in cols:
                        avg_val = avgs[cols.index(col_name)]
                        if avg_val is not None:
                            payload[field_name] = avg_val

                if len(payload) == 1:
                    # No hay valores válidos → marcamos como enviados
                    mark_sent_window(table, start_ts, end_ts)
                    windows_sent += 1
                    continue

                ok = send_to_thingspeak(payload, write_key)

                if ok:
                    n = mark_sent_window(table, start_ts, end_ts)
                    log(f"{node_id}--> Subido OK (promedio de {n} medidas) payload={payload}")
                    windows_sent += 1
                    time.sleep(THINGSPEAK_MIN_DELAY)
                else:
                    log(f"{node_id}--> No se pudo subir (queda pendiente)")
                    break

            time.sleep(INTERVAL)

    except Exception as e:
        log(f"ERROR inesperado (no paro el programa): {e}")
        time.sleep(50)