import json
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "gateway.db"
NODES_PATH = BASE_DIR / "nodes.json"

DB_PATH.parent.mkdir(parents=True, exist_ok=True)

with open(NODES_PATH, "r", encoding="utf-8") as f:
    nodes = json.load(f)

con = sqlite3.connect(DB_PATH)
cur = con.cursor()

for node_id, cfg in nodes.items():
    table = cfg["table"]
    cols = cfg["db_columns"]

    # Build SQL for dynamic columns
    dyn_cols_sql = ",\n        ".join([f"{c} REAL" for c in cols])

    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {table} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_utc TEXT NOT NULL,
            {dyn_cols_sql},
            sent INTEGER NOT NULL DEFAULT 0
        );
        """
    )

    # Helpful indexes per table
    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_sent_id ON {table}(sent, id);")
    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_ts ON {table}(ts_utc);")

con.commit()
con.close()

print(f"OK: DB creada desde cero (o actualizada) en {DB_PATH}")
print(f"OK: Nodos cargados desde {NODES_PATH}")
