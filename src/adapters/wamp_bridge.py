import time
from lib.logging import getLogger
from version import VERSION, BUILD_DATE


LOG = getLogger()

class WampBridge:
    def __init__(self, cfg, state, service):
        self.cfg = cfg
        self.state = state
        self.service = service
        self.client = None
        self._last_alive_state = False


    def _pfx(self):
        return self.cfg["wamp"].get("prefix", "org.robits.plantae.")

    def _topic(self, name):
        return self._pfx() + name

    def _addr_suffixes(self):
        out = [self.state.device_id]
        # if self.cfg["wamp"].get("legacy_by_ip", True):
        #     out.append(self.state.ip)
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
        if not self.client:
            LOG.warning("not available self.client: %s", self.client)
            return False

        connected =  bool(self.client.is_connected())
        
        # Add debug logging when connection state changes
        if self._last_alive_state != connected:
            LOG.info("is_alive: state change: %s -> %s", self._last_alive_state, connected)
            pass

        self._last_alive_state = connected
        
        return connected

    async def connect(self):
        import gc
        from protocols.mpautobahn import AutobahnWS

        gc.collect()

        url = self.cfg["wamp"]["url"]
        realm = self.cfg["wamp"].get("realm", "realm1")
        ka = self.cfg.get("wamp", {}).get("keepalive", {})

        self.client = None
        self.state.wamp_ok = False
        LOG.info("connecting: url=%s realm=%s" % (url, realm))
        #LOG.info("connected: %s (%s)", url, realm)

        # Basic gc before connection
        gc.collect()

        # AutobahnWS handles both WebSocket and WAMP session handshake
        # Pass keepalive config for resilience over public internet
        # Simple debug logging
        self.client = AutobahnWS(
            url=url,
            realm=realm,
            ping_interval_s=ka.get("ping_interval_s"),
            idle_timeout_s=ka.get("idle_timeout_s"),
        )
        # Check if we have a pre-resolved host for SNI (Disabled for standard DNS test)
        # server_hostname = self.cfg["wamp"].get("original_host")


        # Set up the on_join callback to handle subscriptions/registrations
        # self.client.on_join(self._on_wamp_join)



        # await self.client.connect()
        # await asyncio.sleep_ms(100)

        try:
            await self.client.connect()
            await self._on_wamp_join()  # do setup now, no Event/Flag needed

        except Exception as e:
            # make sure we drop sockets/refs so GC can reclaim things
            self.state.last_error = e
            try:
                await self.close()
            except Exception:
                pass
            raise

        self.state.wamp_ok = True
        self.state.last_error = None

    async def _on_wamp_join(self):
        """Called when WAMP session is joined - set up subscriptions and registrations"""
        try:
            await self.client.register(self._topic("control"), self.rpc_control)
            await self.client.register(self._topic("calibrate"), self.rpc_calibrate)
            await self.client.register(self._topic("dose"), self.rpc_dose)
            await self.client.register(self._topic("output"), self.rpc_output)
            await self.client.register(self._topic("status"), self.rpc_status)

            await self.client.register(self._topic("restart"), self.rpc_reboot)

            for suf in self._addr_suffixes():
                await self.client.register(self._addr_topic("calibrate", suf), self.rpc_calibrate)
                await self.client.register(self._addr_topic("dose", suf), self.rpc_dose)
                await self.client.register(self._addr_topic("output", suf), self.rpc_output)
                await self.client.register(self._addr_topic("status", suf), self.rpc_status)
                # await self.client.register(self._addr_topic("restart", suf), self.rpc_reboot)
                await self.client.register(self._addr_topic("reset", suf), self.rpc_reset)

            await self.client.subscribe(self._topic("announce.master"), self.on_master)

            await self.publish_announce("announce.online")

            LOG.info("_on_join: completed")
        except Exception as e:
            LOG.error("_on_join: failed")
            raise


    async def close(self):
        import gc
        import uasyncio as asyncio

        if self.client:
            try:
                await self.client.close()
            except Exception:
                pass

        self.client = None
        self.state.wamp_ok = False

        # give uasyncio a chance to run socket close callbacks
        await asyncio.sleep_ms(200)
        gc.collect()

    async def publish_announce(self, topic_name, exclude_me=True):

        # LOG.debug("publish_announce: %s", topic_name)

        # require a joined session
        if not self.client.is_connected():
            LOG.warning("publish_announce: is_connected false  %s" % topic_name)
            return

        payload = {"id": self.state.device_id, "ip": self.state.ip,
                   "ver": VERSION,
                   "build": BUILD_DATE,
                   "ts": time.time(),
                   "config": self.cfg
                   }
        
        options = {}
        if exclude_me is not None:
             options["exclude_me"] = exclude_me

        pub_id = await self.client.publish(self._topic(topic_name), kwargs=payload, acknowledge=False, options=options)
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
        # LOG.debug("publish_status")

        if not self.client: return
        snap = self.state.snapshot()
        for suf in self._addr_suffixes():
            await self.client.publish(self._addr_topic("status", suf), kwargs=snap)

    async def on_master(self, args, kwargs, details):
        await self.publish_announce("announce.online")

    async def rpc_control(self, args, kwargs, details):
        if not self.service:
            return {"error": "service_not_initialized"}
        if "all" in kwargs:
            return self.service.set_all_switches(bool(kwargs["all"]))
        if "switch" in kwargs:
            idx, on = int(kwargs["switch"][0]), bool(kwargs["switch"][1])
            ok = self.service.set_switch(idx, on)
            if ok:
                await self.publish_switch(idx, on)
            return ok
        if "patch_cfg" in kwargs and isinstance(kwargs["patch_cfg"], dict):
            return self.service.patch_config(kwargs["patch_cfg"])
        return False

    async def rpc_calibrate(self, args, kwargs, details):
        if not self.service:
            return {"error": "service_not_initialized"}
        if kwargs.get("type") == "flow" and "calibration" in kwargs:
            cal = int(kwargs["calibration"])
            return self.service.patch_config({"flow": {"calibration": cal}})
        return False

    async def rpc_dose(self, args, kwargs, details):
        if not self.service:
            return {"error": "service_not_initialized"}
        """Handle dosing RPC calls"""
        action = kwargs.get("action", "status")
        
        if action == "start":
            quantity = kwargs.get("quantity", 0.0)
            if quantity <= 0:
                return {"error": "invalid_quantity", "quantity": quantity}
            
            success = await self.service.start_dose(quantity, is_manual=True)
            if success:
                return {"status": "started", "quantity": quantity}
            else:
                return {"error": "failed_to_start"}
                
        elif action == "stop":
            success = self.service.stop_dose()
            return {"status": "stopped" if success else "not_active"}
            
        elif action == "status":
            return self.service.get_dose_status()
            
        else:
            return {"error": "unknown_action", "action": action}

    async def rpc_output(self, args, kwargs, details):
        if not self.service:
            return {"error": "service_not_initialized"}
        """Handle output control RPC calls"""
        name = kwargs.get("name", "pwm")
        duty = kwargs.get("duty", 1.0)
        action = kwargs.get("action")
        
        if name == "pwm":
            if action == "release":
                self.service.set_pwm_manual(0, override=False, source="rpc")
                return {"status": "released"}
            else:
                self.service.set_pwm_manual(duty, override=True, source="rpc")
                return {"status": "set", "duty": duty}
            
        elif name == "pca9685":
            return {"status": "pca9685_not_implemented"}
            
        else:
            return {"error": "unknown_output", "name": name}


    async def rpc_status(self, args, kwargs, details):
        if not self.service:
            return {"error": "service_not_initialized"}
        """Get device status including dosing information"""
        return self.service.get_status()

    async def rpc_reset(self, args, kwargs, details):
        if not self.service:
            return {"error": "service_not_initialized"}
        return self.service.reset_counters()

    async def rpc_reboot(self, args, kwargs, details):
        if not self.service:
            return {"error": "service_not_initialized"}
        t = 1
        if args:
            try: t = int(args[0])
            except Exception: pass
        if "timeout" in kwargs:
            try: t = int(kwargs["timeout"])
            except Exception: pass
        
        return self.service.reboot(t)
