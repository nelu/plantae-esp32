import time
import uasyncio as asyncio
from protocols.mpautobahn import AutobahnWS, parse_ws_url
from lib.logging import getLogger
from version import VERSION, BUILD_DATE


LOG = getLogger(__name__)

class WampBridge:
    def __init__(self, cfg, state, switchbank, config_mgr, schedule_reboot, dosing_controller=None):
        self.cfg = cfg
        self.state = state
        self.switchbank = switchbank
        self.config_mgr = config_mgr
        self.schedule_reboot = schedule_reboot
        self.dosing_controller = dosing_controller
        self.client = None
        self._graceful_close = False  # Set True on reboot to send announce.offline

    def _pfx(self):
        return self.cfg["wamp"].get("prefix", "org.robits.plantae.")

    def _topic(self, name):
        return self._pfx() + name

    def _addr_suffixes(self):
        out = [self.state.device_id]
        if self.cfg["wamp"].get("legacy_by_ip", True):
            out.append(self.state.ip)
        seen=set(); uniq=[]
        for x in out:
            if x and x not in seen:
                uniq.append(x); seen.add(x)
        return uniq

    def _addr_topic(self, base_name, suffix):
        return self._pfx() + ("%s.%s" % (base_name, suffix))

    def is_alive(self):
        """
        Connectivity check for the current WAMP client (AutobahnWS).
        """
        c = self.client
        if not c:
            return False
        is_connected = getattr(c, "is_connected", None)
        connected = bool(is_connected()) if callable(is_connected) else False
        
        # Add debug logging when connection state changes
        if hasattr(self, '_last_alive_state'):
            if self._last_alive_state != connected:
                LOG.warn("connection state changed: %s -> %s", self._last_alive_state, connected)
                pass
        self._last_alive_state = connected
        
        return connected

    async def connect(self):
        import gc
        
        url = self.cfg["wamp"]["url"]
        realm = self.cfg["wamp"].get("realm", "realm1")
        ka = self.cfg.get("wamp", {}).get("keepalive", {})

        self.client = None
        self.state.wamp_ok = False

        # Simple debug logging
        LOG.info("CONN: url=%s realm=%s", url, realm)

        # Basic gc before connection
        gc.collect()

        # Parse ws:// / wss:// URL without urllib (reuse helper from ws_async)
        scheme, host, port, path = parse_ws_url(url)
        use_ssl = (scheme == "wss")
        
        # Check if we have a pre-resolved host for SNI (Disabled for standard DNS test)
        # server_hostname = self.cfg["wamp"].get("original_host")
        server_hostname = None

        # AutobahnWS handles both WebSocket and WAMP session handshake
        # Pass keepalive config for resilience over public internet
        self.client = AutobahnWS(
            host=host,
            port=port,
            realm=realm,
            path=path,
            use_ssl=use_ssl,
            ping_interval_s=ka.get("ping_interval_s"),
            idle_timeout_s=ka.get("idle_timeout_s"),
            server_hostname=server_hostname,
        )

        # Set up the on_join callback to handle subscriptions/registrations
        self.client.on_join(self._on_wamp_join)
        
        await self.client.connect()
        await asyncio.sleep_ms(100)

        self.state.wamp_ok = True
        self.state.last_error = None
        LOG.info("connected: %s (%s)" % (url, realm))

    async def _on_wamp_join(self):
        """Called when WAMP session is joined - set up subscriptions and registrations"""

        await self.client.register(self._topic("control"), self.rpc_control)
        await self.client.register(self._topic("calibrate"), self.rpc_calibrate)
        await self.client.register(self._topic("dose"), self.rpc_dose)
        await self.client.register(self._topic("status"), self.rpc_status)

        await self.client.register(self._topic("restart"), self.rpc_reboot)

        for suf in self._addr_suffixes():
            await self.client.register(self._addr_topic("calibrate", suf), self.rpc_calibrate)
            await self.client.register(self._addr_topic("dose", suf), self.rpc_dose)
            await self.client.register(self._addr_topic("status", suf), self.rpc_status)
            # await self.client.register(self._addr_topic("reboot", suf), self.rpc_reboot)
            await self.client.register(self._addr_topic("reset", suf), self.rpc_reset)

        await self.client.subscribe(self._topic("announce.master"), self.on_master)

        await self.publish_announce("announce.online")
        
        LOG.info("Setup completed")

    async def close(self):
        import gc
        import uasyncio as asyncio

        if self.client:
            # Only send announce.offline on graceful shutdown (e.g. reboot)
            if self._graceful_close:
                try:
                    await self.publish_announce("announce.offline")
                except Exception:
                    pass
            try:
                await self.client.close()
            except Exception:
                pass

        self.client = None
        self.state.wamp_ok = False
        self._graceful_close = False

        # give uasyncio a chance to run socket close callbacks
        await asyncio.sleep_ms(200)
        gc.collect()

    async def publish_announce(self, topic_name, exclude_me=None):
        # LOG.debug("publish_announce: %s", topic_name)

        c = self.client
        if not c:
            return
        # require a joined session
        is_connected = getattr(c, "is_connected", None)
        if callable(is_connected):
            if not is_connected():
                return

        payload = {"id": self.state.device_id, "ip": self.state.ip,
                   "ver": VERSION,
                   "build": BUILD_DATE,
                   "ts": time.time()}
        
        options = {}
        if exclude_me is not None:
             options["exclude_me"] = exclude_me

        pub_id = await c.publish(self._topic(topic_name), kwargs=payload, acknowledge=True, options=options)
        # LOG.debug("Announce published: %s pub_id=%s", topic_name, pub_id)

    async def publish_switch(self, idx, on):
        if not self.client: return
        await self.client.publish(self._topic("switch"), args=[int(idx), int(bool(on))])

    async def publish_sense(self):
        if not self.client: return
        payload = {"sense": 0, "data": [round(self.state.volume_l, 2), round(self.state.flow_lpm, 2)]}
        for suf in self._addr_suffixes():
            await self.client.publish(self._addr_topic("sense", suf), kwargs=payload)

    async def publish_status(self):
        if not self.client: return
        snap = self.state.snapshot()
        for suf in self._addr_suffixes():
            await self.client.publish(self._addr_topic("status", suf), kwargs=snap)

    async def on_master(self, args, kwargs, details):
        await self.publish_announce("announce.online")

    async def rpc_control(self, args, kwargs, details):
        if "all" in kwargs and self.switchbank:
            ok = self.switchbank.set_all(bool(kwargs["all"]))
            self.state.switches[:] = self.switchbank.values[:]
            return ok
        if "switch" in kwargs and self.switchbank:
            idx, on = int(kwargs["switch"][0]), bool(kwargs["switch"][1])
            ok = self.switchbank.set(idx, on)
            if ok:
                self.state.switches[:] = self.switchbank.values[:]
                await self.publish_switch(idx, on)
            return ok
        if "patch_cfg" in kwargs and isinstance(kwargs["patch_cfg"], dict):
            self.config_mgr.update(kwargs["patch_cfg"])
            self.config_mgr.save()
            return True
        return False

    async def rpc_calibrate(self, args, kwargs, details):
        if kwargs.get("type") == "flow" and "calibration" in kwargs:
            cal = int(kwargs["calibration"])
            self.cfg["flow"]["calibration"] = cal
            self.config_mgr.update({"flow": {"calibration": cal}})
            self.config_mgr.save()
            return True
        return False

    async def rpc_dose(self, args, kwargs, details):
        """Handle dosing RPC calls"""
        if not self.dosing_controller:
            return {"error": "dosing_not_available"}
            
        action = kwargs.get("action", "status")
        
        if action == "start":
            quantity = kwargs.get("quantity", 0.0)
            if quantity <= 0:
                return {"error": "invalid_quantity", "quantity": quantity}
            
            success = await self.dosing_controller.start_dose(quantity)
            if success:
                return {"status": "started", "quantity": quantity}
            else:
                return {"error": "failed_to_start"}
                
        elif action == "stop":
            success = self.dosing_controller.stop_dose()
            return {"status": "stopped" if success else "not_active"}
            
        elif action == "status":
            return self.dosing_controller.get_dose_status()
            
        else:
            return {"error": "unknown_action", "action": action}


    async def rpc_status(self, args, kwargs, details):
        """Get device status including dosing information"""
        return self.state.snapshot()

    async def rpc_reset(self, args, kwargs, details):
        # if kwargs.get("flow") or kwargs.get("interval") == "flow":
            self.state.volume_l = 0.0
            self.state.pulses = 0
            return True
        # return False

    async def rpc_reboot(self, args, kwargs, details):
        t = 1
        if args:
            try: t = int(args[0])
            except Exception: pass
        if "timeout" in kwargs:
            try: t = int(kwargs["timeout"])
            except Exception: pass
        
        # Send announce.offline before reboot
        self._graceful_close = True
        try:
            await self.publish_announce("announce.offline")
        except Exception:
            pass
        
        self.schedule_reboot(t)
        return True
