#!/usr/bin/env python3
"""
view_gateway_db.py
─────────────────────────────────────────────────────────────────────────────
SQLite gateway.db visualiser — saves a PNG image of the graphs.
No GUI, no X11, no XQuartz. Works over plain SSH from any OS.
─────────────────────────────────────────────────────────────────────────────
"""

import os
import sys
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

import matplotlib
matplotlib.use("Agg")   # Non-interactive backend — no display needed
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd


# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────
SCRIPT_DIR  = Path(__file__).resolve().parent
DB_PATH     = SCRIPT_DIR / "gateway.db"
EXPORT_DIR  = SCRIPT_DIR / "exports"
EXPORT_DIR.mkdir(exist_ok=True)   # create if it doesn't exist

KNOWN_TIME_COLS = [
    "ts_utc", "timestamp", "time", "datetime",
    "date", "created_at", "received_at", "ts",
]
EXCLUDE_PATTERNS = {"sent"}
# Exact column names to always exclude (case-insensitive).
# Use this to exclude a column named exactly "id" without
# filtering out columns containing the substring "id" (e.g. "humidity").
EXCLUDE_COLUMNS = {"id"}


# ─────────────────────────────────────────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────────────────────────────────────────
def get_user_tables(con: sqlite3.Connection) -> list[str]:
    cur = con.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name;"
    )
    return [row[0] for row in cur.fetchall()]


def get_columns(con: sqlite3.Connection, table: str) -> list[str]:
    cur = con.execute(f"PRAGMA table_info('{table}');")
    return [row[1] for row in cur.fetchall()]


def detect_time_column(columns: list[str]) -> str | None:
    lower = {c.lower(): c for c in columns}
    for candidate in KNOWN_TIME_COLS:
        if candidate in lower:
            return lower[candidate]
    return None


def sample_time_values(con: sqlite3.Connection, table: str, col: str, n: int = 20) -> list:
    cur = con.execute(
        f"SELECT [{col}] FROM [{table}] WHERE [{col}] IS NOT NULL LIMIT ?", (n,)
    )
    return [row[0] for row in cur.fetchall()]


def classify_time_type(samples: list) -> str:
    for v in samples:
        if isinstance(v, str):
            return "iso"
        if isinstance(v, (int, float)):
            return "epoch_ms" if v > 32_503_680_000 else "epoch_s"
    return "iso"


def load_data(
    con: sqlite3.Connection,
    table: str,
    time_col: str,
    time_type: str,
    since: datetime,
) -> pd.DataFrame:
    if time_type == "iso":
        s1 = since.strftime("%Y-%m-%dT%H:%M:%S")
        s2 = since.strftime("%Y-%m-%d %H:%M:%S")
        query = (
            f"SELECT * FROM [{table}] "
            f"WHERE [{time_col}] >= ? OR [{time_col}] >= ? "
            f"ORDER BY [{time_col}] ASC"
        )
        return pd.read_sql_query(query, con, params=(s1, s2))
    elif time_type == "epoch_s":
        query = f"SELECT * FROM [{table}] WHERE [{time_col}] >= ? ORDER BY [{time_col}] ASC"
        return pd.read_sql_query(query, con, params=(since.timestamp(),))
    else:
        query = f"SELECT * FROM [{table}] WHERE [{time_col}] >= ? ORDER BY [{time_col}] ASC"
        return pd.read_sql_query(query, con, params=(since.timestamp() * 1000,))


def coerce_time(df: pd.DataFrame, time_col: str, time_type: str) -> pd.DataFrame:
    if time_type == "iso":
        df[time_col] = pd.to_datetime(df[time_col], utc=True, errors="coerce")
    elif time_type == "epoch_s":
        df[time_col] = pd.to_datetime(df[time_col], unit="s", utc=True, errors="coerce")
    else:
        df[time_col] = pd.to_datetime(df[time_col], unit="ms", utc=True, errors="coerce")
    df[time_col] = df[time_col].dt.tz_convert(None)
    return df.dropna(subset=[time_col]).sort_values(time_col)


def pick_numeric_cols(df: pd.DataFrame, time_col: str) -> list[str]:
    # try to turn anything that looks numeric into a number
    lower_exacts = {col.lower() for col in EXCLUDE_COLUMNS}
    for c in df.columns:
        if c == time_col:
            continue
        if c.lower() in lower_exacts:
            continue
        if any(p in c.lower() for p in EXCLUDE_PATTERNS):
            continue
        df[c] = pd.to_numeric(df[c], errors="coerce")

    num = df.select_dtypes(include=["number"]).columns.tolist()
    return [
        c for c in num
        if c != time_col and c.lower() not in lower_exacts
        and not any(p in c.lower() for p in EXCLUDE_PATTERNS)
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Terminal prompts
# ─────────────────────────────────────────────────────────────────────────────
def prompt_table(tables: list[str]) -> str:
    print("\nAvailable tables:")
    for i, t in enumerate(tables, 1):
        print(f"  [{i}] {t}")
    while True:
        raw = input("\nSelect table number: ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(tables):
            return tables[int(raw) - 1]
        print(f"  ✗ Enter a number between 1 and {len(tables)}.")


def prompt_days() -> int:
    while True:
        raw = input("How many days back do you want to plot? ").strip()
        if raw.isdigit() and int(raw) > 0:
            return int(raw)
        print("  ✗ Enter a positive integer.")


def prompt_time_col(columns: list[str]) -> str | None:
    print("\n  ✗ Could not auto-detect a time column.")
    print(f"  Detected columns: {columns}")
    raw = input("  Type the name of the time column (or 'q' to quit): ").strip()
    if raw.lower() == "q":
        return None
    if raw in columns:
        return raw
    print(f"  ✗ '{raw}' not found in columns.")
    return None


def prompt_save_csv(df: pd.DataFrame, table: str, n_days: int):
    raw = input("\nDo you want to save the data as CSV? [y/N]: ").strip().lower()
    if raw == "y":
        ts_str   = datetime.now().strftime("%Y%m%d")
        filename = f"{ts_str}_{table}_{n_days}_days.csv"
        out_path = EXPORT_DIR / filename
        df.to_csv(out_path, index=False)
        print(f"✓ CSV saved: {out_path}")
    else:
        print("  CSV not saved.")


# ─────────────────────────────────────────────────────────────────────────────
# Plot → PNG
# ─────────────────────────────────────────────────────────────────────────────
def save_figure(
    df: pd.DataFrame,
    time_col: str,
    num_cols: list[str],
    table: str,
    n_days: int,
) -> Path:
    n = len(num_cols)
    fig, axes = plt.subplots(
        n, 1,
        figsize=(14, 3.5 * n),
        sharex=True,
        squeeze=False,
    )
    fig.subplots_adjust(left=0.10, right=0.97, top=0.93, bottom=0.10, hspace=0.40)

    title = f"Table: {table}  —  last {n_days} day(s)  ({len(df)} rows)"
    fig.suptitle(title, fontsize=13, fontweight="bold")

    for i, col in enumerate(num_cols):
        ax = axes[i][0]
        ax.plot(df[time_col], df[col], linewidth=1.2, marker=".", markersize=3)
        ax.set_ylabel(col, fontsize=9)
        ax.grid(True, linestyle="--", alpha=0.5)

        locator   = mdates.AutoDateLocator()
        formatter = mdates.ConciseDateFormatter(locator)
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(formatter)
        ax.tick_params(axis="x", rotation=30, labelsize=8)

        if i == n - 1:
            ax.set_xlabel("Time (UTC)", fontsize=9)

    ts_str   = datetime.now().strftime("%Y%m%d")
    filename = f"{ts_str}_{table}_{n_days}_days.png"
    out_path = EXPORT_DIR / filename

    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out_path


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main():
    if not DB_PATH.exists():
        sys.exit(f"✗ Database not found: {DB_PATH}")

    con = sqlite3.connect(str(DB_PATH))

    try:
        tables = get_user_tables(con)
        if not tables:
            sys.exit("✗ No user tables found in the database.")

        table  = prompt_table(tables)
        n_days = prompt_days()

        # Detect time column
        columns  = get_columns(con, table)
        time_col = detect_time_column(columns)
        if time_col is None:
            time_col = prompt_time_col(columns)
            if time_col is None:
                sys.exit("Aborted.")

        print(f"\n  → Time column : '{time_col}'")

        # Classify time format
        samples = sample_time_values(con, table, time_col)
        if not samples:
            sys.exit(f"✗ Time column '{time_col}' has no data.")

        time_type = classify_time_type(samples)
        print(f"  → Time format : {time_type}")

        # Load and filter data
        since = datetime.now(tz=timezone.utc) - timedelta(days=n_days)
        df    = load_data(con, table, time_col, time_type, since)

        if df.empty:
            print(
                f"\n  ⚠  No rows found in '{table}' for the last {n_days} day(s).\n"
                f"     Try increasing the number of days."
            )
            sys.exit(0)

        print(f"  → Rows loaded : {len(df)}")

        df       = coerce_time(df, time_col, time_type)
        num_cols = pick_numeric_cols(df, time_col)

        if not num_cols:
            sys.exit(
                f"✗ No plottable numeric columns found in '{table}'.\n"
                f"  Columns: {list(df.columns)}"
            )

        print(f"  → Columns     : {num_cols}")

        # Save PNG
        png_path = save_figure(df, time_col, num_cols, table, n_days)
        print(f"\n✓ Graph saved : {png_path}")

        # Optionally save CSV
        prompt_save_csv(df, table, n_days)

    finally:
        con.close()


if __name__ == "__main__":
    main()

