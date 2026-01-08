#!/usr/bin/env python3
"""
Utility script to reduce memory pressure during WAMP connections.
This can be imported and used to temporarily reduce task frequency.
"""

import gc
try:
    import uasyncio as asyncio
except ImportError:
    import asyncio

class TaskThrottler:
    """Utility to temporarily reduce task frequency during critical operations."""
    
    def __init__(self):
        self.throttled = False
        self.original_intervals = {}
    
    def enable_throttling(self):
        """Enable throttling mode - reduces task frequency."""
        self.throttled = True
        print("Task throttling enabled - reducing background task frequency")
    
    def disable_throttling(self):
        """Disable throttling mode - restore normal task frequency."""
        self.throttled = False
        print("Task throttling disabled - restoring normal task frequency")
    
    def get_flow_interval(self, default_ms=1000):
        """Get flow sensor reading interval (throttled during SSL connections)."""
        if self.throttled:
            return default_ms * 3  # 3x slower during throttling
        return default_ms
    
    def get_dosing_interval(self, default_ms=500):
        """Get dosing controller update interval (throttled during SSL connections)."""
        if self.throttled:
            return default_ms * 2  # 2x slower during throttling
        return default_ms
    
    def should_skip_pwm_schedule(self):
        """Whether to skip PWM schedule updates during throttling."""
        return self.throttled
    
    async def throttle_during_operation(self, operation_coro):
        """
        Run an operation with task throttling enabled.
        
        Usage:
            throttler = TaskThrottler()
            result = await throttler.throttle_during_operation(ssl_connect())
        """
        self.enable_throttling()
        try:
            # Give other tasks a moment to see the throttling flag
            await asyncio.sleep_ms(100)
            
            result = await operation_coro
            return result
        finally:
            self.disable_throttling()
            # Give tasks a moment to restore normal frequency
            await asyncio.sleep_ms(100)

# Global instance that can be imported by other modules
task_throttler = TaskThrottler()

async def reduce_memory_pressure_for_ssl():
    """
    Reduce memory pressure specifically for SSL operations.
    Call this before attempting SSL connections.
    """
    print("Reducing memory pressure for SSL connection...")
    
    # Enable task throttling
    task_throttler.enable_throttling()
    
    # Aggressive garbage collection
    for i in range(20):
        gc.collect()
        await asyncio.sleep_ms(100)
    
    print("Memory pressure reduction complete")

async def restore_normal_operation():
    """
    Restore normal task operation after SSL connection.
    """
    print("Restoring normal task operation...")
    
    # Disable task throttling
    task_throttler.disable_throttling()
    
    # Final cleanup
    gc.collect()
    
    print("Normal operation restored")

if __name__ == "__main__":
    # Test the throttling system
    async def test_throttling():
        print("Testing task throttling system...")
        
        print(f"Normal flow interval: {task_throttler.get_flow_interval()}")
        print(f"Normal dosing interval: {task_throttler.get_dosing_interval()}")
        
        await reduce_memory_pressure_for_ssl()
        
        print(f"Throttled flow interval: {task_throttler.get_flow_interval()}")
        print(f"Throttled dosing interval: {task_throttler.get_dosing_interval()}")
        
        await asyncio.sleep(2)
        
        await restore_normal_operation()
        
        print(f"Restored flow interval: {task_throttler.get_flow_interval()}")
        print(f"Restored dosing interval: {task_throttler.get_dosing_interval()}")
    
    try:
        asyncio.run(test_throttling())
    except KeyboardInterrupt:
        print("\nTest interrupted")