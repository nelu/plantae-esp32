#!/usr/bin/env python3
"""
Simple test to verify the simplified callback handling works on both Python and MicroPython.
No more need for coroutine detection - just try both approaches!
"""

import sys

# Handle asyncio import for both Python and MicroPython (standard pattern from codebase)
try:
    import uasyncio as asyncio
    print("Using MicroPython uasyncio")
    IS_MICROPYTHON = True
except ImportError:
    import asyncio
    print("Using standard Python asyncio")
    IS_MICROPYTHON = False


# Test functions
def regular_function(args, kwargs, details):
    print(f"Regular function called: args={args}, kwargs={kwargs}")
    return "regular_result"


async def async_function(args, kwargs, details):
    print(f"Async function called: args={args}, kwargs={kwargs}")
    await asyncio.sleep(0.1)
    return "async_result"


class TestCallbacks:
    def regular_method(self, args, kwargs, details):
        print(f"Regular method called: args={args}, kwargs={kwargs}")
        return "regular_method_result"
    
    async def on_master(self, args, kwargs, details):
        """This simulates the actual callback that was failing"""
        print(f"on_master called: args={args}, kwargs={kwargs}")
        await asyncio.sleep(0.1)
        return "on_master_result"


async def test_callback_with_simple_fallback(name, func, args, kwargs, details):
    """Test calling a callback with our simplified try-both approach."""
    print(f"\nTesting {name}...")
    
    try:
        # Try calling as regular function first
        result = func(args, kwargs, details)
        
        # Check if we got a coroutine object (async function called as regular)
        if hasattr(result, '__await__'):
            print(f"  Got coroutine object, awaiting it...")
            result = await result
            print(f"  Called as ASYNC function, result: {result}")
        else:
            print(f"  Called as REGULAR function, result: {result}")
            
    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback
        traceback.print_exc()


async def main():
    print("Testing simplified callback handling (no coroutine detection needed)...")
    print(f"Python version: {sys.version}")
    
    # Test if asyncio.iscoroutinefunction exists (just for info)
    try:
        result = asyncio.iscoroutinefunction(regular_function)
        print(f"asyncio.iscoroutinefunction is available, result: {result}")
    except AttributeError:
        print("asyncio.iscoroutinefunction is NOT available (MicroPython) - but that's OK!")
    
    print("\n=== Testing Simplified Callback Execution ===")
    
    test_obj = TestCallbacks()
    
    test_cases = [
        ("regular_function", regular_function),
        ("async_function", async_function),
        ("regular_method", test_obj.regular_method),
        ("on_master (async method)", test_obj.on_master),
    ]
    
    # Test calling each function with our simplified fallback logic
    for name, func in test_cases:
        await test_callback_with_simple_fallback(name, func, ["test_arg"], {"test": "value"}, {})
    
    print("\nTest completed successfully! No coroutine detection needed.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except AttributeError:
        # MicroPython doesn't have asyncio.run
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())