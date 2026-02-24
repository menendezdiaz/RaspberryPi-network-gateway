# RaspberryPi-network-gateway

LoRa-based sensor network with a Raspberry Pi gateway:\
**LoRa / Serial → Raspberry Pi → SQLite → ThingSpeak** (with backlog
recovery).

------------------------------------------------------------------------

## Repository layout

-   `ts_gateway/`\
    Raspberry Pi gateway:
    -   `receiver.py` receives and parses sensor lines (via serial/LoRa)
    -   Stores them in a local SQLite database (resilient to internet
        outages)
    -   `uploader.py` uploads unsent rows to ThingSpeak and marks them
        as sent
    -   Timestamps are the **reception time** (stored and later uploaded
        using `created_at`)
-   `sensor_node/`\
    Arduino/ESP32 firmware examples for LoRa sender nodes.\
    Example: `emisor0218.ino`

------------------------------------------------------------------------

## Quick start (Raspberry Pi)

### 1) Clone

``` bash
git clone <YOUR_GITHUB_REPO_URL>
cd RaspberryPi-network-gateway/ts_gateway
```

### 2) Create your local nodes config (DO NOT COMMIT)

``` bash
cp nodes.example.json nodes.json
nano nodes.json   # put your real ThingSpeak write keys here
```

### 3) Install dependencies (if applicable)

If your gateway uses only the Python standard library, skip this.\
Otherwise (recommended):

``` bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 4) Initialize the database

``` bash
python3 init_db.py
```

### 5) Run manually (debug)

``` bash
python3 receiver.py
# in another terminal
python3 uploader.py
```

### 6) systemd (production)

See `ts_gateway/README.md` for systemd service setup and operation.

------------------------------------------------------------------------

## Sensor nodes

Firmware examples are in `sensor_node/`.\
Flash the corresponding `.ino` to an ESP32 node connected to an E32 LoRa
module.

------------------------------------------------------------------------

## Secrets policy

-   **Never commit real ThingSpeak keys.**
-   `ts_gateway/nodes.json` is ignored by git on purpose.
-   Use `ts_gateway/nodes.example.json` as a template.

------------------------------------------------------------------------

## More details

Gateway documentation: `ts_gateway/README.md`
