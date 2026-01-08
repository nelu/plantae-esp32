"""
Memory optimization utilities for MicroPython ESP32.
Helps manage memory pressure during critical operations like SSL connections.
"""

import gc
try:
    import uasyncio as asyncio
except ImportError:
    import asyncio


class MemoryOptimizer:
    """Helper class for aggressive memory management during critical operations."""
    
    @staticmethod
    async def prepare_for_ssl():
        """
        Ultra-aggressive memory preparation for SSL connections.
        Should be called before attempting SSL handshake.
        """
        # Force immediate garbage collection
        for i in range(15):  # Even more aggressive
            gc.collect()
            await asyncio.sleep_ms(100)  # Longer delays
        
        # Extended delay for memory allocator to settle
        await asyncio.sleep_ms(1000)  # 1 second delay
        
        # Final GC pass
        gc.collect()
    
    @staticmethod
    async def cleanup_after_error():
        """
        Cleanup after memory allocation errors.
        """
        for i in range(20):  # More cleanup passes
            gc.collect()
            await asyncio.sleep_ms(150)
        
        # Extended recovery period
        await asyncio.sleep_ms(2000)  # 2 second recovery
    
    @staticmethod
    def get_memory_info():
        """
        Get current memory information if available.
        Returns dict with memory stats or empty dict if not available.
        """
        info = {}
        try:
            if hasattr(gc, 'mem_free'):
                info['free'] = gc.mem_free()
            if hasattr(gc, 'mem_alloc'):
                info['allocated'] = gc.mem_alloc()
        except:
            pass
        return info
    
    @staticmethod
    async def force_defragment():
        """
        Force memory defragmentation through multiple allocation/deallocation cycles.
        """
        # Create and destroy some temporary objects to force defragmentation
        temp_objects = []
        try:
            # Multiple rounds of allocation/deallocation to force defragmentation
            for round_num in range(3):
                # Allocate some temporary memory in different sizes
                for i in range(5):
                    try:
                        temp_objects.append(bytearray(512))
                        await asyncio.sleep_ms(10)
                    except:
                        break
                
                # Clear and collect
                temp_objects.clear()
                gc.collect()
                await asyncio.sleep_ms(200)
                
                # Try larger blocks
                for i in range(3):
                    try:
                        temp_objects.append(bytearray(1024))
                        await asyncio.sleep_ms(10)
                    except:
                        break
                
                # Clear and collect again
                temp_objects.clear()
                gc.collect()
                await asyncio.sleep_ms(300)
            
        except:
            # If we can't allocate, that's fine - just clean up
            pass
        finally:
            temp_objects.clear()
            gc.collect()
            await asyncio.sleep_ms(500)
    
    @staticmethod
    async def extreme_cleanup():
        """
        Most aggressive cleanup for severe memory pressure.
        """
        # Multiple rounds of different cleanup strategies
        for round_num in range(5):
            # Force garbage collection
            gc.collect()
            await asyncio.sleep_ms(200)
            
            # Try to force defragmentation
            try:
                # Allocate and immediately free small blocks
                temp = []
                for i in range(10):
                    try:
                        temp.append(bytearray(256))
                    except:
                        break
                temp.clear()
                del temp
            except:
                pass
            
            gc.collect()
            await asyncio.sleep_ms(300)
        
        # Final extended delay
        await asyncio.sleep_ms(1000)


async def with_memory_optimization(coro):
    """
    Context manager-like function to run a coroutine with memory optimization.
    
    Usage:
        result = await with_memory_optimization(some_ssl_operation())
    """
    await MemoryOptimizer.prepare_for_ssl()
    try:
        return await coro
    except OSError as e:
        if e.args and e.args[0] == 16:
            await MemoryOptimizer.extreme_cleanup()
        raise