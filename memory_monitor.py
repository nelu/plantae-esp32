#!/usr/bin/env python3
"""
Memory monitoring script for MicroPython ESP32.
Helps identify memory usage patterns and potential issues.
"""

import gc
import time
try:
    import uasyncio as asyncio
except ImportError:
    import asyncio

class MemoryMonitor:
    """Simple memory monitoring utility."""
    
    def __init__(self):
        self.baseline = None
        self.samples = []
    
    def get_memory_info(self):
        """Get current memory information."""
        info = {}
        try:
            if hasattr(gc, 'mem_free'):
                info['free'] = gc.mem_free()
            if hasattr(gc, 'mem_alloc'):
                info['allocated'] = gc.mem_alloc()
        except:
            pass
        return info
    
    def set_baseline(self):
        """Set current memory as baseline."""
        gc.collect()
        self.baseline = self.get_memory_info()
        print(f"Baseline memory: {self.baseline}")
    
    def sample(self, label=""):
        """Take a memory sample."""
        gc.collect()
        info = self.get_memory_info()
        
        if self.baseline and 'free' in info and 'free' in self.baseline:
            diff = info['free'] - self.baseline['free']
            print(f"Memory {label}: free={info['free']} (diff={diff:+d})")
        else:
            print(f"Memory {label}: {info}")
        
        self.samples.append((label, info, time.ticks_ms()))
    
    def report(self):
        """Generate memory usage report."""
        print("\n--- Memory Usage Report ---")
        if self.baseline:
            print(f"Baseline: {self.baseline}")
        
        for i, (label, info, timestamp) in enumerate(self.samples):
            if self.baseline and 'free' in info and 'free' in self.baseline:
                diff = info['free'] - self.baseline['free']
                print(f"{i+1:2d}. {label:20s}: free={info['free']:6d} (diff={diff:+6d})")
            else:
                print(f"{i+1:2d}. {label:20s}: {info}")

async def monitor_ssl_connection():
    """Monitor memory during SSL connection attempts."""
    
    monitor = MemoryMonitor()
    monitor.set_baseline()
    
    try:
        from protocols.mpautobahn import AutobahnWS
        
        monitor.sample("after imports")
        
        # Test connection to your SSL endpoint
        client = AutobahnWS(
            host="plantae.robits.org",
            port=443,
            realm="realm1",
            path="/ws",
            use_ssl=True
        )
        
        monitor.sample("after client create")
        
        print("Attempting SSL connection...")
        await client.connect()
        print("SSL connection successful!")
        
        monitor.sample("after connect")
        
        # Test basic WAMP functionality
        await asyncio.sleep(1)
        
        monitor.sample("after sleep")
        
        await client.close()
        print("Connection closed successfully")
        
        monitor.sample("after close")
        
        # Final cleanup
        del client
        gc.collect()
        
        monitor.sample("after cleanup")
        monitor.report()
        
        return True
        
    except OSError as e:
        print(f"Connection failed with OSError: {e}")
        if e.args and e.args[0] == 16:
            print("OSError 16 detected - memory allocation issue")
        monitor.sample("after error")
        monitor.report()
        return False
    except Exception as e:
        print(f"Connection failed with error: {e}")
        monitor.sample("after error")
        monitor.report()
        return False

async def main():
    """Run memory monitoring test."""
    
    print("Memory Monitor for SSL Connection Issues")
    print("=" * 50)
    
    # Show initial memory state
    gc.collect()
    initial = gc.mem_free() if hasattr(gc, 'mem_free') else 0
    print(f"Initial free memory: {initial}")
    
    # Run the test
    success = await monitor_ssl_connection()
    
    print(f"\nTest result: {'SUCCESS' if success else 'FAILED'}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nMonitoring interrupted by user")