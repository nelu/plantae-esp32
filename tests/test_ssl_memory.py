#!/usr/bin/env python3
"""
Simple test script to verify SSL connection memory optimizations.
This can be run on MicroPython to test the changes.
"""

import gc
import time
try:
    import uasyncio as asyncio
except ImportError:
    import asyncio

async def test_ssl_connection():
    """Test SSL connection with memory monitoring"""
    
    print("Testing SSL connection memory optimizations...")
    
    # Monitor initial memory
    gc.collect()
    initial_free = gc.mem_free() if hasattr(gc, 'mem_free') else 0
    print(f"Initial free memory: {initial_free}")
    
    try:
        from protocols.mpautobahn import AutobahnWS
        
        # Test connection to your SSL endpoint
        client = AutobahnWS(
            host="plantae.robits.org",
            port=443,
            realm="realm1",
            path="/ws",
            use_ssl=True
        )
        
        print("Attempting SSL connection...")
        await client.connect()
        print("SSL connection successful!")
        
        # Monitor memory after connection
        gc.collect()
        connected_free = gc.mem_free() if hasattr(gc, 'mem_free') else 0
        print(f"Free memory after connect: {connected_free}")
        
        # Test basic WAMP functionality
        await asyncio.sleep(1)
        
        await client.close()
        print("Connection closed successfully")
        
        # Monitor memory after cleanup
        gc.collect()
        final_free = gc.mem_free() if hasattr(gc, 'mem_free') else 0
        print(f"Final free memory: {final_free}")
        
        return True
        
    except OSError as e:
        print(f"Connection failed with OSError: {e}")
        if e.args and e.args[0] == 16:
            print("OSError 16 detected - memory allocation issue")
        return False
    except Exception as e:
        print(f"Connection failed with error: {e}")
        return False

async def main():
    """Run multiple connection attempts to test reliability"""
    
    success_count = 0
    total_attempts = 5
    
    for i in range(total_attempts):
        print(f"\n--- Attempt {i+1}/{total_attempts} ---")
        
        # Force garbage collection before each attempt
        for _ in range(3):
            gc.collect()
            await asyncio.sleep_ms(100)
        
        success = await test_ssl_connection()
        if success:
            success_count += 1
        
        # Wait between attempts
        await asyncio.sleep(2)
    
    print(f"\n--- Results ---")
    print(f"Successful connections: {success_count}/{total_attempts}")
    print(f"Success rate: {success_count/total_attempts*100:.1f}%")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nTest interrupted by user")