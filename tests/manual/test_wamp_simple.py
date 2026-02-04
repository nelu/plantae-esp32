#!/usr/bin/env python3
"""
Simple test to verify WAMP subscription fix
Run this on the device to test if subscriptions work
"""

import time
import uasyncio as asyncio
from protocols.mpautobahn import AutobahnWS, parse_ws_url
from logging import getLogger, basicConfig, DEBUG

# Configure logging
basicConfig(level=DEBUG)
LOG = getLogger("test_wamp")

async def on_master_received(args, kwargs, details):
    LOG.info("🎯 MASTER RECEIVED! args=%s kwargs=%s details=%s", args, kwargs, details)

async def test_subscription():
    LOG.info("Starting WAMP subscription test...")
    
    # Connect to WAMP
    scheme, host, port, path = parse_ws_url("ws://192.168.4.106/ws")
    client = AutobahnWS(host=host, port=port, realm="realm1", path=path, use_ssl=False)
    
    try:
        await client.connect()
        LOG.info("Connected to WAMP")
        
        # Subscribe to master announcements
        sub_id = await client.subscribe("org.robits.plantae.announce.master", on_master_received)
        LOG.info("Subscribed with ID: %s", sub_id)
        
        # Publish a test message to trigger our own subscription
        await asyncio.sleep(1)
        LOG.info("Publishing test master announcement...")
        await client.publish("org.robits.plantae.announce.master", kwargs={"time": time.time()})
        
        # Wait for the message
        LOG.info("Waiting for subscription callback...")
        await asyncio.sleep(3)
        
        LOG.info("Test completed")
        
    except Exception as e:
        LOG.error("Test failed: %s", e)
        import sys
        sys.print_exception(e)
    finally:
        await client.close()

if __name__ == "__main__":
    asyncio.run(test_subscription())