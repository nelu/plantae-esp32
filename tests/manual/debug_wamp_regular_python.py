#!/usr/bin/env python3
"""
Debug script to test WAMP subscriptions using regular Python and autobahn library
This will help us understand if the issue is in our MicroPython implementation
"""

import asyncio
import time
from autobahn.asyncio.wamp import ApplicationSession, ApplicationRunner

class WampDebugSession(ApplicationSession):
    def __init__(self, config=None):
        super().__init__(config)
        self.subscription_received = False
        self.rpc_called = False
        
    async def onJoin(self, details):
        print(f"🚀 Joined WAMP session: {details}")
        
        # Register test RPC
        await self.register(self.rpc_debug_test, "org.robits.plantae.debug_test")
        print("✅ Registered RPC: org.robits.plantae.debug_test")
        
        # Subscribe to master announcements
        await self.subscribe(self.on_master_debug, "org.robits.plantae.announce.master")
        print("✅ Subscribed to: org.robits.plantae.announce.master")
        
        # Subscribe to test topic
        await self.subscribe(self.on_test_debug, "org.robits.plantae.test.debug")
        print("✅ Subscribed to: org.robits.plantae.test.debug")
        
        # Run tests
        await self.run_tests()
        
    async def on_master_debug(self, *args, **kwargs):
        print("🎯 MASTER ANNOUNCEMENT RECEIVED!")
        print(f"  args: {args}")
        print(f"  kwargs: {kwargs}")
        self.subscription_received = True
        
        # Respond with online announcement
        try:
            await self.publish("org.robits.plantae.announce.online", 
                             id="debug-device", ip="192.168.4.1", ts=time.time())
            print("✅ Sent announce.online response")
        except Exception as e:
            print(f"❌ Failed to send announce.online: {e}")
    
    async def on_test_debug(self, *args, **kwargs):
        print("🧪 TEST MESSAGE RECEIVED!")
        print(f"  args: {args}")
        print(f"  kwargs: {kwargs}")
    
    def rpc_debug_test(self, *args, **kwargs):
        print("🔧 RPC DEBUG_TEST CALLED!")
        print(f"  args: {args}")
        print(f"  kwargs: {kwargs}")
        self.rpc_called = True
        return {"status": "debug_test_ok", "timestamp": time.time()}
    
    async def test_publish(self):
        """Test publishing to see if basic WAMP works"""
        print("📤 Testing publish...")
        try:
            await self.publish("org.robits.plantae.test.debug", 
                             test="publish_works", ts=time.time())
            print("✅ Publish successful")
            return True
        except Exception as e:
            print(f"❌ Publish failed: {e}")
            return False
    
    async def test_rpc_call(self):
        """Test calling our own RPC"""
        print("📞 Testing RPC call...")
        try:
            result = await self.call("org.robits.plantae.debug_test", "test_arg")
            print(f"✅ RPC call successful: {result}")
            return True
        except Exception as e:
            print(f"❌ RPC call failed: {e}")
            return False
    
    async def simulate_master_announce(self):
        """Simulate a master announcement"""
        print("📢 Simulating master announcement...")
        try:
            await self.publish("org.robits.plantae.announce.master", time=time.time())
            print("✅ Master announcement sent")
            return True
        except Exception as e:
            print(f"❌ Master announcement failed: {e}")
            return False
    
    async def run_tests(self):
        """Run comprehensive WAMP tests"""
        print("🚀 Starting WAMP debug tests...")
        
        # Wait a bit for everything to settle
        await asyncio.sleep(1)
        
        # Test 1: Basic publish
        await self.test_publish()
        await asyncio.sleep(1)
        
        # Test 2: RPC call
        await self.test_rpc_call()
        await asyncio.sleep(1)
        
        # Test 3: Simulate master announcement (should trigger our subscription)
        await self.simulate_master_announce()
        await asyncio.sleep(2)  # Give time for subscription to fire
        
        # Test 4: Check if subscription was received
        if self.subscription_received:
            print("✅ Subscription test PASSED")
        else:
            print("❌ Subscription test FAILED - no message received")
        
        # Test 5: Check if RPC was called
        if self.rpc_called:
            print("✅ RPC test PASSED")
        else:
            print("❌ RPC test FAILED - RPC was not called")
        
        print("🏁 Debug tests completed")
        
        # Keep running to monitor for external messages
        print("👂 Listening for external messages (press Ctrl+C to stop)...")
        try:
            while True:
                await asyncio.sleep(5)
                print("Still connected and listening...")
        except KeyboardInterrupt:
            print("Stopping debug session...")
            self.disconnect()

if __name__ == "__main__":
    runner = ApplicationRunner(
        url="ws://192.168.4.106/ws",
        realm="realm1"
    )
    
    try:
        runner.run(WampDebugSession)
    except KeyboardInterrupt:
        print("Debug session interrupted")