# WAMP Surface (MicroPython side)

Reference implementation of the ESP32 WAMP client used for tests and fixtures. Source: `src/adapters/wamp_bridge.py`, WAMP transport: `src/protocols/mpautobahn/client.py`.

## Session & Namespacing
- Connects to `cfg["wamp"].url` with realm `cfg["wamp"].get("realm", "realm1")` and optional `sni_host`.
- Topic/prefix helper: `org.robits.plantae.` by default (override via `cfg["wamp"].get("prefix")`).
- Addressable suffixes: device id (e.g. `plantae-1234`). Prefixed topics become `org.robits.plantae.<name>` or `org.robits.plantae.<name>.<device_id>`.
- On join: registers RPCs, subscribes to `announce.master`, publishes `announce.online`, then starts ping keepalive.

## Subscriptions (device listens)
- `org.robits.plantae.announce.master`
  - Purpose: master ping; when received, device re-publishes `announce.online`.

## RPC Procedures (registered by device)
Base procedures exist both unsuffixed and per-device (`<name>.<device_id>`) unless noted. Calls use kwargs unless args shown.

### `control`
- Purpose: switch control or config patch.
- Request (all switches on):
```json
{"all": true}
```
- Request (single switch):
```json
{"switch": [2, 1]}
```
- Request (config patch):
```json
{"patch_cfg": {"flow": {"calibration": 1200}}}
```
- Response: `true` on success, otherwise `false`.

### `calibrate`
- Purpose: flow calibration update.
- Request:
```json
{"type": "flow", "calibration": 1234}
```
- Response: `true` when applied, else `false`.

### `dose`
- Purpose: manual dosing lifecycle.
- Start request:
```json
{"action": "start", "quantity": 1.25}
```
- Start responses:
```json
{"status": "started", "quantity": 1.25}
```
or
```json
{"error": "alert_active", "reason": "timeout", "ts": 1893452000}
```
or `{"error": "invalid_quantity", "quantity": -1}` / `{"error": "failed_to_start"}`.
- Stop request:
```json
{"action": "stop"}
```
- Stop response:
```json
{"status": "stopped"}
```
or `{"status": "not_active"}`.
- Status request (default):
```json
{"action": "status"}
```
- Status response:
```json
{"active": false, "target_l": 0.0, "dosed_l": 0.0, "remaining_l": 0.0, "duration_s": 0}
```

### `alert`
- Purpose: manage alert records.
- List request (or empty kwargs): `{}`.
- List response:
```json
{"dosing": {"message": "timeout", "ts": 1893452000}}
```
- Clear request:
```json
{"action": "clear", "kind": "dosing"}
```
- Clear response: `{"status": "cleared", "kind": "dosing"}` or `{"error": "missing_kind"}`.
- Set request:
```json
{"action": "set", "kind": "custom", "message": "note"}
```
- Set response: `{"status": "set", "kind": "custom"}`.

### `output`
- Purpose: PWM override control.
- Set duty request:
```json
{"name": "pwm", "duty": 0.42}
```
- Release request:
```json
{"name": "pwm", "action": "release"}
```
- Response:
```json
{"status": "set", "duty": 0.42}
```
or `{"status": "released"}` or `{"error": "unknown_output", "name": "x"}`.

### `status`
- Purpose: fetch current device snapshot.
- Request: `{}`.
- Response: see full structure below.

### `restart`
- Purpose: schedule reboot (base only).
- Request examples:
```json
{}
```
or args `[5]` or kw `{ "timeout": 5 }`.
- Response: `true`.

### `reset`
- Purpose: reset flow counters (per-device only).
- Request: `{}`.
- Response: `true`.

### Dose RPC payloads
- Start: `{"action": "start", "quantity": 1.25}` → `{ "status": "started", "quantity": 1.25 }` or `{ "error": "alert_active"|"invalid_quantity"|"failed_to_start", ... }`
- Stop: `{"action": "stop"}` → `{ "status": "stopped" | "not_active" }`
- Status (default): `{"action": "status"}` or empty → `{"active": bool, "target_l": float, "dosed_l": float, "remaining_l": float, "duration_s": float}`

### Alert RPC payloads
- List (default): `{}` or `{"action": "list"}` → `{ "dosing": {"message": "timeout", "ts": 1710000000}, ... }`
- Clear: `{"action": "clear", "kind": "dosing"}` → `{ "status": "cleared", "kind": "dosing" }` or error
- Set (manual/testing): `{"action": "set", "kind": "custom", "message": "note"}` → `{ "status": "set", "kind": "custom" }`

### Status RPC response shape
Example response from `status` or periodic publishes:
```json
{
  "id": "plantae-1234",
  "ip": "192.168.1.50",
  "utc": 1893456000,
  "uptime_s": 7345,
  "heap": 84200,
  "flow": {"lps": 0.2, "lpm": 12.0, "vol_l": 3.45, "pulses": 1280},
  "out": {"switches": [0,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0], "pwm": 0.5},
  "dosing": {"active": false, "target_l": 0.0, "dosed_l": 0.0, "remaining_l": 0.0, "duration_s": 0},
  "health": {"signal": -55, "ntp": true, "wamp": true, "err": ""},
  "stats": {"last_dose_ts": 1893452000, "lifetime_volume_l": 123.4, "pwm_runtime_s": 5400.0, "alerts": {}}
}
```

## Publications (device emits)
Topics use base prefix unless noted; per-device topics append `<device_id>`.

- `announce.online` (base, no suffix)
  - When: on session join and when `announce.master` is received.
  - Payload (kwargs): `{"id": "plantae-1234", "ip": "192.168.1.50", "ver": "x.y.z", "build": "2025-01-01", "ts": 1893456100, "config": { ... full cfg ... }}`
  - Options: `exclude_me` respected when provided (defaults to `True`).

- `status.<device_id>` (per-device)
  - When: every ~1s while connected (`task_wamp` loop) once session_ready.
  - Payload: same structure as Status RPC response.

- `sense.<device_id>` (per-device)
  - When: `publish_sense` is invoked (currently commented in supervisor loop).
  - Payload: `{ "sense": 0, "data": [<volume_l>, <flow_lpm>] }` e.g. `{ "sense": 0, "data": [3.45, 12.0] }`.

- `switch` (base)
  - When: `rpc_control` toggles a switch successfully.
  - Payload (args): `[idx, on]` where `idx` is int, `on` is 0/1.

## Client Integration Examples

### Python (Autobahn asyncio)
```python
import asyncio
from autobahn.asyncio.wamp import ApplicationSession, ApplicationRunner

PREFIX = "org.robits.plantae."
DEVICE = "plantae-1234"

class Client(ApplicationSession):
    async def onJoin(self, details):
        # Call status
        status = await self.call(PREFIX + "status." + DEVICE)
        print("status", status)

        # Start a dose
        res = await self.call(PREFIX + "dose." + DEVICE, **{"action": "start", "quantity": 0.5})
        print("dose start", res)

        # Subscribe to status stream
        await self.subscribe(self.on_status, PREFIX + "status." + DEVICE)

    def on_status(self, args=None, kwargs=None, details=None):
        print("status event", kwargs)

async def main():
    runner = ApplicationRunner(url="wss://router.example/ws", realm="realm1")
    await runner.run(Client, start_loop=False)
    await asyncio.Future()  # keep running

if __name__ == "__main__":
    asyncio.run(main())
```

### JavaScript / TypeScript (AutobahnJS)
```ts
import { Connection } from 'autobahn';

const PREFIX = 'org.robits.plantae.';
const DEVICE = 'plantae-1234';

const conn = new Connection({
  url: 'wss://router.example/ws',
  realm: 'realm1',
  protocols: ['wamp.2.json'],
});

conn.onopen = async (session) => {
  const status = await session.call(PREFIX + 'status.' + DEVICE);
  console.log('status', status);

  const res = await session.call(PREFIX + 'dose.' + DEVICE, [], { action: 'start', quantity: 0.5 });
  console.log('dose start', res);

  await session.subscribe(PREFIX + 'status.' + DEVICE, (args, kwargs) => {
    console.log('status event', kwargs);
  });
};

conn.onclose = (reason) => {
  console.warn('closed', reason);
};

conn.open();
```

## Test Hints
- Use the base procedures for fleet-wide actions; use suffixed ones for targeted calls when multiple devices share a router.
- For integration tests, mock a WAMP router that captures publishes on `announce.online` and `status.<device_id>` and assert structure matches examples above.
- Keep the prefix configurable in tests; derive expected topics from `cfg["wamp"].get("prefix", "org.robits.plantae.")`.
