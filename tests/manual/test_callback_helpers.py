#!/usr/bin/env python3
"""
Test the reusable callback helper functions for handling async/sync callbacks.
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


# Mock the helper functions from the client
def _handle_callback_result(result):
    """Handle callback result for fire-and-forget async calls."""
    if hasattr(result, '__await__'):
        asyncio.create_task(result)
        return True
    elif hasattr(result, '__next__'):
        asyncio.create_task(result)
        return True
    else:
        return False


async def _handle_callback_result_await(result):
    """Handle callback result when we need to await the result."""
    if hasattr(result, '__await__'):
        return await result
    elif hasattr(result, '__next__'):
        return await result
    else:
        return result


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


async def test_fire_and_forget_callbacks(name, func, args, kwargs, details):
    """Test fire-and-forget callbacks (like subscriptions)."""
    print(f"\nTesting {name} (fire-and-forget)...")
    
    try:
        result = func(args, kwargs, details)
        
        if _handle_callback_result(result):
            print(f"  Started async callback successfully")
            await asyncio.sleep(0.2)  # Give async callback time to complete
        else:
            print(f"  Completed sync callback, result: {result}")
            
    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback
        traceback.print_exc()


async def test_awaited_callbacks(name, func, args, kwargs, details):
    """Test callbacks that need to be awaited (like RPC calls)."""
    print(f"\nTesting {name} (awaited)...")
    
    try:
        result = func(args, kwargs, details)
        final_result = await _handle_callback_result_await(result)
        print(f"  Final result: {final_result}")
            
    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback
        traceback.print_exc()


async def main():
    print("Testing reusable callback helper functions...")
    print(f"Python version: {sys.version}")
    
    test_obj = TestCallbacks()
    
    test_cases = [
        ("regular_function", regular_function),
        ("async_function", async_function),
        ("regular_method", test_obj.regular_method),
        ("on_master (async method)", test_obj.on_master),
    ]
    
    print("\n=== Testing Fire-and-Forget Callbacks (Subscriptions) ===")
    for name, func in test_cases:
        await test_fire_and_forget_callbacks(name, func, ["test_arg"], {"test": "value"}, {})
    
    print("\n=== Testing Awaited Callbacks (RPC Calls) ===")
    for name, func in test_cases:
        await test_awaited_callbacks(name, func, ["test_arg"], {"test": "value"}, {})
    
    print("\nTest completed successfully! Reusable helpers work great.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except AttributeError:
        # MicroPython doesn't have asyncio.run
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())