# Refactored MicroPython port (ESP32)

Refactor goals:
- Domain logic (state/scheduling/controllers) separated from networking and drivers
- Stable device addressing (`sense.<device_id>`, `status.<device_id>`)
- Optional legacy addressing by IP (`sense.<ip>`, `status.<ip>`) for backwards compatibility
- Supervisor task model with reconnect/backoff

Install:
Copy folders to the device root:
- /protocols
- /drivers
- /domain
- /adapters
- /app
And place main.py and config.json at the root.

HTTP:
- GET /status
- GET /config
- POST /config (merge patch + persist)
- POST /reboot

WAMP:
Prefix defaults to `org.robits.plantae.`
Publishes:
- announce.online / announce.offline
- switch
- sense.<device_id> (+ optional sense.<ip>)
- status.<device_id> (+ optional status.<ip>)
RPC:
- control
  - `{"update": "<release-tag>"}` triggers OTA update from GitHub release json
- calibrate (+ calibrate.<device_id> and optionally calibrate.<ip>)
- reset.<device_id> (+ optional reset.<ip>)
- reboot (+ reboot.<device_id> and optionally reboot.<ip>)

WebSocket supports ws:// and **optional** wss:// (best-effort; depends on your MicroPython build).
Keepalive pings are enabled by default (see `wamp.keepalive`).
