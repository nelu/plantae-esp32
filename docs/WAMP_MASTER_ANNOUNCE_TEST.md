# WAMP Master Announce Test

## Overview
This document describes how to test the WAMP `announce.master` subscription functionality.

## Issues Identified and Fixed

### Issue 1: EVENT Message Parsing Bug (FIXED)
The AutobahnWS client had a bug in EVENT message parsing that prevented subscription callbacks from working.

**Problem:**
- WAMP EVENT format: `[EVENT, subscription_id, publication_id, details, args, kwargs]`
- The code was incorrectly parsing `publication_id`, causing subscription callbacks to fail
- Publishing worked fine, but subscriptions were broken

**Solution:**
1. Fixed EVENT message parsing in `src/protocols/mpautobahn/client.py`
2. Added comprehensive debug logging to track subscription issues
3. Added proper error handling for malformed messages

### Issue 2: MicroPython asyncio.iscoroutinefunction Missing (FIXED)
MicroPython's `uasyncio` module doesn't include the `iscoroutinefunction` method, causing AttributeError.

**Problem:**
```
AttributeError: iscoroutinefunction
Traceback (most recent call last):
File "protocols/mpautobahn/client.py", line 301, in _handle_wamp_message
File "uasyncio.py", line 1, in __getattr__
```

**Solution:**
Instead of trying to detect if a function is a coroutine, we use a much simpler approach:
1. Call the function normally
2. Check if the result has `__await__` attribute (indicating it's a coroutine)
3. Check if the result has `__next__` attribute (MicroPython async functions return generators)
4. If it is a coroutine or generator, await it or create a task
5. This works for both sync and async functions without needing `iscoroutinefunction`
6. **NEW:** Created reusable helper functions `_handle_callback_result()` and `_handle_callback_result_await()` to eliminate code duplication

### Issue 3: WAMP Subscriptions Before Session Join (FIXED)
Subscriptions and registrations were being set up immediately after connection, but WAMP protocol requires them to be done after the session is properly joined.

**Problem:**
- Subscriptions were created during connection setup
- WAMP callbacks weren't being executed because the session wasn't fully established
- The `on_master` callback was returning generator objects but not being awaited

**Solution:**
1. Moved all subscriptions and registrations to an `on_join` callback
2. The `on_join` callback is executed after the WAMP session is properly established
3. This follows the standard WAMP protocol pattern used by autobahn libraries

## Testing the Fix

### Method 1: RPC Call
```javascript
// From web client or WAMP client
call("org.robits.plantae.test_master")
```

### Method 2: Direct Publish
```javascript
// From web client or WAMP client  
publish("org.robits.plantae.announce.master", {time: "2026-01-08T12:43:00Z"})
```

### Expected Behavior
1. Device connects to WAMP router
2. **NEW:** Device logs "WAMP session joined - setting up subscriptions and registrations"
3. Device receives the `announce.master` message
4. **NEW:** Device logs: `"🎯 on_master received: args=... kwargs=..."`
5. Device responds with `announce.online` publication
6. **NEW:** Device logs: `"📢 on_master: published announce.online"`
7. Debug logs show successful subscription callback execution
8. **No more AttributeError: iscoroutinefunction errors**
9. **No more generator objects being returned without awaiting**

## Why Web Client Worked
The web client uses the standard `autobahn-js` library which correctly implements WAMP message parsing, while the MicroPython implementation had these parsing and compatibility bugs.

## Debug Configuration
Enable debug logging in `config.json`:
```json
{
  "logging": {
    "level": "DEBUG",
    "loggers": {
      "wamp_bridge": "DEBUG",
      "wamp_debug": "DEBUG"
    }
  }
}
```

## Available Tests
- `tests/manual/debug_wamp_subscriptions.py` - MicroPython debug script
- `tests/manual/debug_wamp_regular_python.py` - Regular Python debug script  
- `tests/manual/test_wamp_simple.py` - Simple MicroPython test
- `tests/manual/test_coroutine_detection.py` - Test the original callback handling
- `tests/manual/test_callback_helpers.py` - Test the reusable callback helper functions
- `tests/integration/test_wamp_subscriptions.py` - Full integration test

## Compatibility Notes
The fix ensures compatibility between:
- Regular Python (with full asyncio module)
- MicroPython (with limited uasyncio module)
- Both sync and async callback functions
- Graceful error recovery for misdetected function types