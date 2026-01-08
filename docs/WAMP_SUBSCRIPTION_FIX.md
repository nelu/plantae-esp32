# WAMP Subscription Fix

## Problem
The WAMP subscribe functionality was broken - the controller didn't receive subscription messages even though:
- Publishing worked fine (announce.online on connect)
- RPC calls worked fine
- Web client subscriptions worked correctly

## Root Cause
**EVENT Message Parsing Bug in AutobahnWS Client**

The WAMP EVENT message format according to the specification is:
```
[EVENT, SUBSCRIBED.Subscription|id, PUBLISHED.Publication|id, Details|dict, PUBLISH.Arguments|list, PUBLISH.ArgumentsKw|dict]
```

However, the AutobahnWS client in `src/protocols/mpautobahn/client.py` was incorrectly parsing these messages:

**Before (Broken):**
```python
elif code == C.EVENT:
    sub_id = msg[1]                    # ✅ Correct
    details = msg[3]                   # ❌ Wrong! This is publication_id
    args = msg[4]                      # ❌ Wrong! Off by one
    kwargs = msg[5]                    # ❌ Wrong! Off by one
```

**After (Fixed):**
```python
elif code == C.EVENT:
    sub_id = msg[1]                    # ✅ Subscription ID
    pub_id = msg[2]                    # ✅ Publication ID (was missing!)
    details = msg[3]                   # ✅ Details
    args = msg[4]                      # ✅ Arguments
    kwargs = msg[5]                    # ✅ Keyword arguments
```

## Files Modified

### `src/protocols/mpautobahn/client.py`
1. **Fixed EVENT message parsing** - Added publication_id field and corrected field offsets
2. **Added comprehensive debug logging** - Track message processing and subscription callbacks
3. **Added error handling** - Proper handling of malformed messages
4. **Enhanced SUBSCRIBED logging** - Track subscription registration

## Testing the Fix

### Method 1: Using RPC Test
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
1. Device receives the `announce.master` message
2. Device logs show: `"on_master received: args=... kwargs=..."`
3. Device responds with `announce.online` publication
4. Debug logs show successful subscription callback execution

## Why Web Client Worked
The web client uses the standard `autobahn-js` library which correctly implements WAMP message parsing. Our MicroPython implementation had this parsing bug.

## Debug Logging
With the fix, you'll now see detailed debug logs:
```
DEBUG:wamp_debug:RX WAMP msg: code=36 len=6 msg=[36, 123, 456, {}, [], {"time": 1641234567}]
DEBUG:wamp_debug:Processing EVENT message: [36, 123, 456, {}, [], {"time": 1641234567}]
DEBUG:wamp_debug:EVENT: sub_id=123 pub_id=456 details={} args=[] kwargs={"time": 1641234567}
DEBUG:wamp_debug:Found callback for sub_id 123: True
DEBUG:wamp_debug:Calling subscription callback...
DEBUG:wamp_bridge:on_master received: args=[] kwargs={'time': 1641234567}
DEBUG:wamp_debug:Subscription callback completed successfully
```

## Configuration
Ensure debug logging is enabled in `config.json`:
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