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

## Remote Access (Tailscale)

The Raspberry Pi gateway can be accessed remotely via Tailscale:

### SSH Connection

```bash
ssh pi@<TAILSCALE_IP>
```

Once connected via SSH, you can:

-   Monitor services: `sudo systemctl status ts_receiver`
-   View data: `python3 ~/ts_gateway/data/view_gateway_db.py`
-   Download exports: `scp -r pi@<TAILSCALE_IP>:/home/pi/ts_gateway/data/exports ./`

### VS Code Remote Access

Using the "Remote - SSH" extension:

1.  Install the extension from VS Code Marketplace
2.  Click **>< (Remote)** in the bottom-left corner
3.  Select "Connect to Host..."
4.  Enter `ssh pi@<TAILSCALE_IP>`
5.  Open `/home/pi/ts_gateway` and browse files directly

This allows you to:

-   View logs and data files
-   Download CSV exports and graphs
-   Monitor the gateway from any location

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
