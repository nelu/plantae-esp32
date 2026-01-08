#!/usr/bin/env python3
"""
Debug script to test WAMP subscriptions and RPC bindings
This will help identify where the issue is occurring
"""

import time
import uasyncio as asyncio
import ujson as json
from protocols.mpautobahn import AutobahnWS, parse_ws_url
from lib.logging import getLogger, basicConfig, DEBUG

# Configure debug logging
basicConfig(level=DEBUG, format="%(asctime)s %(levelname)s:%(name)s:%(message)s", datefmt="%H:%M:%S")
LOG = getLogger("debug_wamp")

class WampDebugger:
    def __init__(self, url="ws://192.168.4.106/ws", realm="realm1"):
        self.url = url
        self.realm = realm
        self.client = None
        self.subscription_received = False
        self.rpc_called = False
        
    async def connect(self):
        LOG.info("Connecting to %s realm %s", self.url, self.realm)
        
        # Parse URL
        scheme, host, port, path = parse_ws_url(self.url)
        use_ssl = (scheme == "wss")
        
        # Create client
        self.client = AutobahnWS(
            host=host,
            port=port,
            realm=self.realm,
            path=path,
            use_ssl=use_ssl,
            ping_interval_s=25,
            idle_timeout_s=180,
        )
        
        await self.client.connect()
        LOG.info("Connected successfully")
        
        # Register test RPC
        await self.client.register("org.robits.plantae.debug_test", self.rpc_debug_test)
        LOG.info("Registered RPC: org.robits.plantae.debug_test")
        
        # Subscribe to master announcements
        sub_id = await self.client.subscribe("org.robits.plantae.announce.master", self.on_master_debug)
        LOG.info("Subscribed to org.robits.plantae.announce.master with ID: %s", sub_id)
        
        # Also subscribe to a test topic
        test_sub_id = await self.client.subscribe("org.robits.plantae.test.debug", self.on_test_debug)
        LOG.info("Subscribed to org.robits.plantae.test.debug with ID: %s", test_sub_id)
        
        return True
        
    async def on_master_debug(self, args, kwargs, details):
        LOG.info("🎯 MASTER ANNOUNCEMENT RECEIVED!")
        LOG.info("  args: %s", args)
        LOG.info("  kwargs: %s", kwargs)
        LOG.info("  details: %s", details)
        self.subscription_received = True
        
        # Respond with online announcement
        try:
            await self.client.publish("org.robits.plantae.announce.online", 
                                    kwargs={"id": "debug-device", "ip": "192.168.4.1", "ts": time.time()})
            LOG.info("✅ Sent announce.online response")
        except Exception as e:
            LOG.error("❌ Failed to send announce.online: %s", e)
    
    async def on_test_debug(self, args, kwargs, details):
        LOG.info("🧪 TEST MESSAGE RECEIVED!")
        LOG.info("  args: %s", args)
        LOG.info("  kwargs: %s", kwargs)
        LOG.info("  details: %s", details)
    
    async def rpc_debug_test(self, args, kwargs, details):
        LOG.info("🔧 RPC DEBUG_TEST CALLED!")
        LOG.info("  args: %s", args)
        LOG.info("  kwargs: %s", kwargs)
        LOG.info("  details: %s", details)
        self.rpc_called = True
        return {"status": "debug_test_ok", "timestamp": time.time()}
    
    async def test_publish(self):
        """Test publishing to see if basic WAMP works"""
        LOG.info("📤 Testing publish...")
        try:
            pub_id = await self.client.publish("org.robits.plantae.test.debug", 
                                             kwargs={"test": "publish_works", "ts": time.time()},
                                             acknowledge=True)
            LOG.info("✅ Publish successful, ID: %s", pub_id)
            return True
        except Exception as e:
            LOG.error("❌ Publish failed: %s", e)
            return False
    
    async def test_rpc_call(self):
        """Test calling our own RPC"""
        LOG.info("📞 Testing RPC call...")
        try:
            result = await self.client.call("org.robits.plantae.debug_test", "test_arg")
            LOG.info("✅ RPC call successful: %s", result)
            return True
        except Exception as e:
            LOG.error("❌ RPC call failed: %s", e)
            return False
    
    async def simulate_master_announce(self):
        """Simulate a master announcement"""
        LOG.info("📢 Simulating master announcement...")
        try:
            pub_id = await self.client.publish("org.robits.plantae.announce.master", 
                                             kwargs={"time": time.time()},
                                             acknowledge=True)
            LOG.info("✅ Master announcement sent, ID: %s", pub_id)
            return True
        except Exception as e:
            LOG.error("❌ Master announcement failed: %s", e)
            return False
    
    async def run_tests(self):
        """Run comprehensive WAMP tests"""
        LOG.info("🚀 Starting WAMP debug tests...")
        
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
            LOG.info("✅ Subscription test PASSED")
        else:
            LOG.error("❌ Subscription test FAILED - no message received")
        
        # Test 5: Check if RPC was called
        if self.rpc_called:
            LOG.info("✅ RPC test PASSED")
        else:
            LOG.error("❌ RPC test FAILED - RPC was not called")
        
        LOG.info("🏁 Debug tests completed")
        
        # Keep running to monitor for external messages
        LOG.info("👂 Listening for external messages (press Ctrl+C to stop)...")
        try:
            while True:
                await asyncio.sleep(5)
                if self.client and self.client.is_connected():
                    LOG.debug("Still connected and listening...")
                else:
                    LOG.error("Connection lost!")
                    break
        except KeyboardInterrupt:
            LOG.info("Stopping debug session...")
    
    async def close(self):
        if self.client:
            await self.client.close()

async def main():
    debugger = WampDebugger()
    try:
        await debugger.connect()
        await debugger.run_tests()
    except Exception as e:
        LOG.error("Debug session failed: %s", e)
        import sys
        sys.print_exception(e)
    finally:
        await debugger.close()

if __name__ == "__main__":
    asyncio.run(main())