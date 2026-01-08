#!/usr/bin/env python3
"""
Integration test for WAMP subscriptions using regular Python autobahn library
This tests the WAMP router and verifies our MicroPython implementation should work
"""

import asyncio
import time
from autobahn.asyncio.wamp import ApplicationSession, ApplicationRunner


class WampSubscriptionTest(ApplicationSession):
    def __init__(self, config=None):
        super().__init__(config)
        self.test_results = {
            "subscription_received": False,
            "rpc_called": False,
            "publish_successful": False,
            "rpc_call_successful": False
        }
        
    async def onJoin(self, details):
        print(f"🚀 Connected to WAMP router: {details.realm}")
        
        try:
            # Register test RPC
            await self.register(self.rpc_test_handler, "org.robits.plantae.test_integration")
            print("✅ Registered RPC: org.robits.plantae.test_integration")
            
            # Subscribe to master announcements
            await self.subscribe(self.on_master_announcement, "org.robits.plantae.announce.master")
            print("✅ Subscribed to: org.robits.plantae.announce.master")
            
            # Subscribe to online announcements
            await self.subscribe(self.on_online_announcement, "org.robits.plantae.announce.online")
            print("✅ Subscribed to: org.robits.plantae.announce.online")
            
            # Run integration tests
            await self.run_integration_tests()
            
        except Exception as e:
            print(f"❌ Setup failed: {e}")
            self.disconnect()
    
    async def on_master_announcement(self, *args, **kwargs):
        print("🎯 Master announcement received!")
        print(f"  args: {args}")
        print(f"  kwargs: {kwargs}")
        self.test_results["subscription_received"] = True
    
    async def on_online_announcement(self, *args, **kwargs):
        print("📡 Online announcement received!")
        print(f"  args: {args}")
        print(f"  kwargs: {kwargs}")
    
    def rpc_test_handler(self, *args, **kwargs):
        print("🔧 RPC test handler called!")
        print(f"  args: {args}")
        print(f"  kwargs: {kwargs}")
        self.test_results["rpc_called"] = True
        return {"status": "integration_test_ok", "timestamp": time.time()}
    
    async def run_integration_tests(self):
        print("\n🧪 Running WAMP integration tests...")
        
        # Wait for setup to complete
        await asyncio.sleep(1)
        
        # Test 1: Publish test
        print("\n📤 Test 1: Publishing test message...")
        try:
            await self.publish("org.robits.plantae.test.integration", 
                             test="integration_publish", timestamp=time.time())
            self.test_results["publish_successful"] = True
            print("✅ Publish test PASSED")
        except Exception as e:
            print(f"❌ Publish test FAILED: {e}")
        
        await asyncio.sleep(1)
        
        # Test 2: RPC call test
        print("\n📞 Test 2: RPC call test...")
        try:
            result = await self.call("org.robits.plantae.test_integration", "integration_test")
            print(f"✅ RPC call test PASSED: {result}")
            self.test_results["rpc_call_successful"] = True
        except Exception as e:
            print(f"❌ RPC call test FAILED: {e}")
        
        await asyncio.sleep(1)
        
        # Test 3: Master announcement test
        print("\n📢 Test 3: Master announcement test...")
        try:
            await self.publish("org.robits.plantae.announce.master", 
                             time=time.time(), test="integration")
            print("✅ Master announcement sent")
        except Exception as e:
            print(f"❌ Master announcement FAILED: {e}")
        
        # Wait for subscription callback
        await asyncio.sleep(2)
        
        # Test 4: Try calling device RPC (if device is connected)
        print("\n🤖 Test 4: Device RPC test...")
        try:
            result = await self.call("org.robits.plantae.test_master")
            print(f"✅ Device RPC test PASSED: {result}")
        except Exception as e:
            print(f"⚠️  Device RPC test FAILED (device may not be connected): {e}")
        
        await asyncio.sleep(2)
        
        # Print test results
        self.print_test_results()
        
        # Keep listening for a bit
        print("\n👂 Listening for device messages (10 seconds)...")
        await asyncio.sleep(10)
        
        print("\n🏁 Integration tests completed")
        self.disconnect()
    
    def print_test_results(self):
        print("\n" + "="*50)
        print("INTEGRATION TEST RESULTS")
        print("="*50)
        
        for test_name, result in self.test_results.items():
            status = "✅ PASS" if result else "❌ FAIL"
            print(f"{test_name}: {status}")
        
        passed = sum(self.test_results.values())
        total = len(self.test_results)
        print(f"\nOverall: {passed}/{total} tests passed")
        
        if passed == total:
            print("🎉 All integration tests PASSED!")
        else:
            print("⚠️  Some integration tests FAILED")
        
        print("="*50)


async def run_integration_test():
    """Run the integration test"""
    print("WAMP Integration Test")
    print("====================")
    print("This test verifies WAMP functionality using the autobahn library")
    print("It should work if the WAMP router is running and accessible")
    print()
    
    runner = ApplicationRunner(
        url="ws://192.168.4.106/ws",
        realm="realm1"
    )
    
    try:
        await runner.run(WampSubscriptionTest, start_loop=False)
    except Exception as e:
        print(f"❌ Integration test failed: {e}")
        print("\nPossible issues:")
        print("- WAMP router not running")
        print("- Network connectivity issues") 
        print("- Incorrect URL or realm")


if __name__ == "__main__":
    try:
        asyncio.run(run_integration_test())
    except KeyboardInterrupt:
        print("\n🛑 Integration test interrupted")
    except Exception as e:
        print(f"\n💥 Integration test crashed: {e}")
        print("\nMake sure you have 'autobahn' installed:")
        print("pip install autobahn")