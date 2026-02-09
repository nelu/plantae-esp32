# Dosing Functionality

This document describes the volumetric dosing functionality implemented in the Plantae system. All schedule times are specified in UTC; convert local time to UTC before writing config or provisioning.

## Configuration

Add the following to your `config.json` under the `schedule` section:

```json
{
  "schedule": {
    "dosing": {
      "start": "08:00",
      "end": "20:10", 
      "output": "pwm",
      "quantity": 0.25
    }
  }
}
```

### Configuration Parameters

- `start`: Start time for dosing window (HH:MM format)
- `end`: End time for dosing window (HH:MM format)
- `output`: Output to use for dosing (currently only "pwm" supported)
- `quantity`: Daily quantity to dose in liters (0.25 = 250ml)

## Flow Sensor Configuration

The system uses the existing flow sensor configuration:

```json
{
  "flow": {
    "type": "YFS401",
    "pin": 34,
    "calibration": 0,
    "read_interval_ms": 1000,
    "pullup_external": true
  }
}
```

## WAMP RPC Methods

### Manual Dosing

Start manual dosing:
```javascript
call("org.robits.plantae.dose", {action: "start", quantity: 0.1})
```

Stop dosing:
```javascript
call("org.robits.plantae.dose", {action: "stop"})
```

Get dosing status:
```javascript
call("org.robits.plantae.dose", {action: "status"})
```

### Device-Specific Methods

You can also call dosing methods on specific devices:
```javascript
call("org.robits.plantae.dose.192.168.1.100", {action: "start", quantity: 0.1})
```

## Automatic Dosing

The system automatically doses the configured quantity once per day at the start of the dosing window. This happens within 1 minute of the start time.

## Safety Features

1. **Time Window**: Dosing only occurs within the configured time window
2. **Timeout**: Dosing automatically stops after 5 minutes to prevent runaway
3. **Single Daily Dose**: Automatic dosing only happens once per day
4. **PWM Override**: Dosing takes priority over scheduled PWM output
5. **Flow Monitoring**: Precise volume measurement using calibrated flow sensor

## Status Monitoring

Dosing status is included in the device status and published via WAMP:

```json
{
  "dosing": {
    "active": true,
    "target_l": 0.25,
    "dosed_l": 0.15,
    "remaining_l": 0.10,
    "duration_s": 45.2
  }
}
```

## Troubleshooting

1. **No dosing occurs**: Check that current time is within the dosing window
2. **Dosing stops early**: Check flow sensor calibration and connections
3. **Inaccurate volumes**: Adjust flow sensor calibration value
4. **Timeout errors**: Check for blockages in the dosing system
