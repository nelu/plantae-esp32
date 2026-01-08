# SSL Memory Optimizations for OSError 16

## Problem Analysis

OSError 16 (EBUSY) during SSL/TLS connections on MicroPython ESP32 occurs due to memory allocation issues during the SSL handshake process. The key insight is that **the test script works perfectly (100% success rate) while the main application fails**, indicating the issue is **memory pressure from concurrent tasks** rather than fundamental SSL problems.

### Root Causes:
1. **8 concurrent tasks** competing for memory: WiFi, NTP, WAMP, HTTP, flow, PWM scheduling, button monitoring, dosing
2. Memory fragmentation from continuous task operations
3. Insufficient contiguous memory during SSL context creation (~84KB free but fragmented)
4. NTP task running continuously causing periodic memory allocations

## Implemented Optimizations

### 1. Task Scheduling Optimization (`supervisor.py`)

**Reduced Concurrent Tasks During WAMP Connection:**
- Start only WiFi and NTP tasks initially
- Wait for both to be ready before starting WAMP
- Start other tasks only AFTER WAMP connection succeeds
- This reduces memory pressure during critical SSL handshake

**NTP Task Optimization:**
- Runs once initially, then uses 6-hour intervals (vs continuous)
- Reduces memory allocations during WAMP connection attempts
- Longer retry intervals (5 minutes vs 1 minute) to reduce pressure

### 2. Enhanced Memory Optimizer (`lib/memory_optimizer.py`)

**Ultra-Aggressive Memory Management:**
- `prepare_for_ssl()`: 15 GC passes + 1 second delay
- `extreme_cleanup()`: 5 rounds of defragmentation + 2 second recovery
- `force_defragment()`: Active memory reorganization through allocation cycles
- Memory info logging for debugging

**Defragmentation Strategy:**
- Multiple rounds of small allocations followed by immediate deallocation
- Forces memory allocator to reorganize fragmented blocks
- Different block sizes (256, 512, 1024 bytes) to target different fragment sizes

### 3. WebSocket Client (`websocket.py`)

**Enhanced SSL Connection:**
- Uses MemoryOptimizer for SSL preparation
- Memory info logging before SSL attempts
- Extreme cleanup on OSError 16 specifically
- Proper socket cleanup on SSL failure

### 4. WAMP Bridge (`wamp_bridge.py`)

**Connection Setup:**
- Memory info logging with free memory reporting
- Uses MemoryOptimizer for connection preparation
- Enhanced error handling and cleanup

### 5. Task Throttling System (`reduce_memory_pressure.py`)

**Optional Background Task Reduction:**
- Can temporarily slow down flow sensor readings (3x slower)
- Can reduce dosing controller updates (2x slower)
- Can pause PWM schedule updates during SSL connections
- Provides framework for future memory pressure management

## Memory Management Strategy

### Startup Sequence (Optimized):
1. **Start WiFi + NTP only** (minimal concurrent tasks)
2. **Wait for both to be ready** (no premature WAMP attempts)
3. **1 second settling delay** after NTP sync
4. **Start WAMP with ultra-aggressive memory prep**
5. **Start other tasks only after WAMP succeeds**

### Before SSL Connection:
1. **Ultra-aggressive preparation**: 15 GC passes with 100ms delays each
2. **Extended settling time**: 1 second delay for memory allocator
3. **Active defragmentation**: Multiple allocation/deallocation cycles
4. **Memory monitoring**: Log free memory before attempts

### After OSError 16:
1. **Extreme cleanup**: 5 rounds of defragmentation
2. **Extended recovery**: 2+ second delays
3. **Longer cooldown**: 8 seconds before retry
4. **Enhanced logging**: Track cleanup progress

## Key Insight: Sequential vs Concurrent Task Startup

**Previous (Problematic):**
```
WiFi + NTP + WAMP + HTTP + Flow + PWM + Dosing (all concurrent)
→ Memory fragmentation during SSL handshake
→ OSError 16
```

**Optimized:**
```
WiFi + NTP → Wait → WAMP → Wait → Other tasks
→ Minimal memory pressure during SSL
→ Higher success rate
```

## Memory Monitoring and Debugging

### Enhanced Logging Output:
```
INFO: WAMP connection attempt - free memory: 85344
INFO: CONN: url=wss://... realm=realm1 mem_free=85344
DEBUG: Memory before SSL: {'allocated': 51312, 'free': 84256}
WARNING: OSError 16 detected - performing extreme memory cleanup
```

### Memory Monitor Script (`memory_monitor.py`):
- Tracks memory usage throughout SSL connection process
- Identifies memory leaks and fragmentation patterns
- Provides detailed reports for debugging

## Expected Results

With these optimizations, you should see:
- **Dramatically reduced OSError 16 frequency** (sequential task startup)
- **Higher first-attempt connection success rate** (less memory pressure)
- **More reliable reconnections** (enhanced cleanup and recovery)
- **Better memory utilization** (active defragmentation)
- **Detailed debugging info** (memory usage logging)

## Testing and Monitoring

Use the provided tools to verify improvements:

```python
# Basic SSL memory test (should still work 100%)
import test_ssl_memory
asyncio.run(test_ssl_memory.main())

# Detailed memory monitoring
import memory_monitor
asyncio.run(memory_monitor.main())

# Task throttling test
import reduce_memory_pressure
asyncio.run(reduce_memory_pressure.test_throttling())
```

## Configuration Options

### NTP Sync Frequency (config.json):
```json
{
  "ntp": {
    "sync_every_s": 21600,  // 6 hours (reduced from continuous)
    "host": "pool.ntp.org"
  }
}
```

### Flow Sensor Frequency (config.json):
```json
{
  "flow": {
    "read_interval_ms": 2000  // Consider increasing from 1000ms
  }
}
```

## Performance Impact

The optimizations add ~2-3 seconds to initial startup but:
- **Significantly improve SSL connection reliability**
- **Reduce memory-related crashes**
- **Provide better long-term stability**
- **Enable detailed debugging of memory issues**

## Fallback Strategy

Multi-layered approach ensures eventual success:
1. **Sequential task startup** - Reduces initial memory pressure
2. **Ultra-aggressive memory prep** - Proactive defragmentation
3. **Enhanced retry logic** - Longer recovery periods for OSError 16
4. **Extreme cleanup** - Force memory reorganization after failures
5. **Extended cooldowns** - Allow memory allocator to fully recover (8+ seconds)

The combination of reduced concurrent tasks during startup and enhanced memory management should resolve the OSError 16 issues while maintaining full functionality.