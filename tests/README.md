# Tests

This directory contains tests for the Plantae MicroPython ESP32 project.

## Test Structure

- `unit/` - Unit tests for individual components and classes
- `integration/` - Integration tests for WAMP, WiFi, and hardware components
- `manual/` - Manual test scripts for debugging and verification

## Running Tests

### Unit Tests
```bash
# Run all unit tests
python -m pytest tests/unit/

# Run specific test file
python -m pytest tests/unit/test_wamp_bridge.py
```

### Integration Tests
```bash
# Run WAMP integration tests (requires WAMP router)
python tests/integration/test_wamp_subscriptions.py

# Run hardware tests (requires ESP32 hardware)
python tests/integration/test_hardware.py
```

### Manual Tests
```bash
# Debug WAMP subscriptions
python tests/manual/debug_wamp_subscriptions.py

# Test master announcements
python tests/manual/test_master_announce.py
```

## Test Requirements

- `pytest` for unit tests
- `autobahn` for WAMP integration tests
- Access to WAMP router for integration tests
- ESP32 hardware for hardware tests

## Adding New Tests

1. **Unit tests**: Add to `tests/unit/test_<component>.py`
2. **Integration tests**: Add to `tests/integration/test_<feature>.py`
3. **Manual tests**: Add to `tests/manual/<test_name>.py`

Follow the existing patterns and ensure tests are well-documented.