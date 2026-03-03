# ts_gateway

**LoRa → Raspberry Pi → SQLite → ThingSpeak Gateway**

`ts_gateway` is a lightweight, production-oriented data gateway designed
to run on a Raspberry Pi. It receives sensor data (typically via LoRa),
stores it locally in SQLite, and uploads it to ThingSpeak with proper
timestamp handling and automatic backlog recovery.

------------------------------------------------------------------------

# 1. Overview

## Purpose

-   Receive sensor data from one or multiple remote nodes
-   Store all data locally in a resilient SQLite database
-   Upload data to ThingSpeak
-   Preserve the original reception timestamp even after internet
    outages
-   Automatically recover and upload backlog when connection is restored

------------------------------------------------------------------------

# 2. System Architecture

\[Sensor Nodes\] \| \| (LoRa / Serial) v \[Raspberry Pi - ts_gateway\]
\| \|-- receiver.py → parses and stores data \|-- SQLite DB → persistent
storage \|-- uploader.py → uploads unsent data \| v \[ThingSpeak
Channels\]

------------------------------------------------------------------------

# 3. How It Works (Technical Summary)

## 3.1 Data Reception

-   The Raspberry Pi receives text lines from sensor nodes.
-   The format is defined per node in `nodes.json`.
-   When a valid line is received:
    -   A UTC timestamp (`ts_utc`) is generated.
    -   Data is inserted into SQLite.
    -   `sent = 0` marks it as pending upload.

Each database row:

-   id (AUTOINCREMENT)
-   ts_utc (ISO8601 UTC, reception time)
-   field1
-   field2
-   ...
-   sent (0 or 1)

Only one timestamp per row is stored: reception time.

------------------------------------------------------------------------

## 3.2 Local Database (Resilience Layer)

-   SQLite database stored locally (e.g., `data/gateway.db`)
-   WAL mode enabled
-   If internet fails:
    -   Data continues to accumulate
    -   Nothing is lost

------------------------------------------------------------------------

## 3.3 Upload to ThingSpeak

`uploader.py`:

-   Periodically fetches rows where `sent = 0`
-   Sends them to ThingSpeak
-   Includes:

`created_at = ts_utc`

This ensures that:

-   Even if data is uploaded hours later,
-   ThingSpeak displays the original reception time,
-   Not the upload time.

After successful upload:

`sent = 1`

------------------------------------------------------------------------

# 4. Configuration

## 4.1 nodes.json

This file defines:

-   Sensor node name
-   Expected message prefix
-   Database table
-   Data columns
-   ThingSpeak channel mapping

Example:

``` json
{
  "teide02": {
    "prefix": "TEST",
    "table": "teide02",
    "columns": ["hum", "temp"],
    "thingspeak": {
      "write_key": "XXXX",
      "fields": {
        "field1": "hum",
        "field2": "temp"
      }
    }
  }
}
```

------------------------------------------------------------------------

# 5. Adding or Modifying Sensors

To add a new sensor node:

## Step 1 --- Edit `nodes.json`

Add a new block with:

-   Unique node name
-   Message prefix
-   Table name
-   Column list
-   ThingSpeak mapping

## Step 2 --- Recreate or Update Database

If it's a new table:

``` bash
python3 init_db.py
```

If you changed columns (recommended in early stages):

``` bash
rm data/gateway.db*
python3 init_db.py
```

No changes are needed in:

-   `receiver.py`
-   `uploader.py`

The system is fully dynamic via JSON.

------------------------------------------------------------------------

# 6. Manual of Use

## Normal Operation

Once deployed:

1.  Connect Raspberry Pi to:
    -   Power
    -   Ethernet (internet)
    -   LoRa receiver module
2.  System starts automatically via systemd services.
3.  No manual intervention required.

------------------------------------------------------------------------

## systemd Services

Two services are typically installed:

-   `ts_receiver.service`
-   `ts_uploader.service`

Check status:

``` bash
sudo systemctl status ts_receiver
sudo systemctl status ts_uploader
```

Restart if needed:

``` bash
sudo systemctl restart ts_receiver
sudo systemctl restart ts_uploader
```

Enable at boot:

``` bash
sudo systemctl enable ts_receiver
sudo systemctl enable ts_uploader
```

------------------------------------------------------------------------

# 7. Internet Failure Behavior

If internet connection drops:

-   receiver continues storing data
-   uploader fails gracefully
-   no crash
-   no data loss

When internet returns:

-   uploader resumes
-   backlog is uploaded
-   original timestamps preserved

------------------------------------------------------------------------

# 8. Data Visualization

The `view_gateway_db.py` script generates visual graphs of your stored sensor data:

-   Automatically detects all tables and numeric columns in `gateway.db`
-   Generates time-series plots for each sensor node
-   Saves PNG images to `data/exports/`
-   Works over SSH without GUI or X11 (headless-friendly)
-   Supports multiple time formats (ISO8601, Unix epoch)

### Usage

```bash
python3 data/view_gateway_db.py
```

The script will:

1.  Scan the gateway database
2.  Create graphs for each table
3.  Save PNG files in `data/exports/` with timestamp

Example output:
-   `data/exports/20260303_readings_teide02_7_days.png`
-   `data/exports/20260303_readings_Cueva_Teide_1_days.csv`

This is useful for:

-   Verifying data quality
-   Inspecting trends remotely
-   Debugging sensor issues
-   Generating reports

------------------------------------------------------------------------

# 9. Replicating the Gateway

## 9.1 Requirements

-   Raspberry Pi (Pi 2 or newer recommended)
-   Python 3.9+
-   SQLite (default)
-   Internet connection
-   ThingSpeak account
-   LoRa module connected to serial

------------------------------------------------------------------------

## 9.2 Installation

Clone repository:

``` bash
git clone <repo>
cd ts_gateway
```

Create virtual environment:

``` bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Initialize database:

``` bash
python3 init_db.py
```

Install systemd services:

``` bash
sudo cp services/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable ts_receiver
sudo systemctl enable ts_uploader
sudo systemctl start ts_receiver
sudo systemctl start ts_uploader
```

------------------------------------------------------------------------

# 10. Data Flow Summary

  Step   Component     Action
  ------ ------------- --------------------------------
  1      Sensor        Sends line
  2      receiver.py   Parses & inserts row
  3      SQLite        Stores with ts_utc
  4      uploader.py   Sends unsent rows
  5      ThingSpeak    Stores with original timestamp

------------------------------------------------------------------------

# 11. Design Philosophy

-   Minimal dependencies
-   Fully local persistence
-   Internet failure tolerant
-   JSON-driven sensor configuration
-   Scalable to multiple nodes
-   Easy to replicate
-   Production-ready for remote deployments

------------------------------------------------------------------------

# 12. Maintenance Tips

-   Periodically backup `gateway.db`
-   Monitor disk usage
-   Monitor systemd service status
-   Validate ThingSpeak API limits

------------------------------------------------------------------------

# 13. Summary

`ts_gateway` is a robust, fault-tolerant Raspberry Pi data gateway that:

-   Receives sensor data
-   Stores everything locally
-   Survives internet outages
-   Uploads with correct timestamps
-   Is fully configurable via JSON
-   Requires no manual interaction once deployed
