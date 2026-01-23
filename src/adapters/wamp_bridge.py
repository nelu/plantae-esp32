import gc
import time

import uasyncio as asyncio

from lib.logging import LOG
from protocols.mpautobahn import AutobahnWS


class WampBridge:
    def __init__(self, cfg, state, service):
        self.cfg = cfg
        self.state = state
        self.service = service
        self.session_ready = False
        self._last_alive_state = False

        url = self.cfg["wamp"]["url"]
        realm = self.cfg["wamp"].get("realm", "realm1")
        ka = self.cfg.get("wamp", {}).get("keepalive", {})
        hostname = self.cfg["wamp"].get("sni_host")

        # Basic gc before connection
        gc.collect()

        # AutobahnWS handles both WebSocket and WAMP session handshake
        # Pass keepalive config for resilience over public internet
        # Simple debug logging
        self.client = AutobahnWS(
            url=url,
            realm=realm,
            sni_host=hostname,
            ping_interval_s=ka.get("ping_interval_s"),
            idle_timeout_s=ka.get("idle_timeout_s"),
        )

    def _pfx(self):
        return self.cfg["wamp"].get("prefix", "org.robits.plantae.")

    def _topic(self, name):
        return self._pfx() + name

    def _addr_suffixes(self):
        out = [self.state.device_id]
        # if self.cfg["wamp"].get("legacy_by_ip", True):
        #     out.append(self.state.ip)
        seen = set()
        uniq = []
        for x in out:
            if x and x not in seen:
                uniq.append(x)
                seen.add(x)
        return uniq

    def _addr_topic(self, base_name, suffix):
        return self._pfx() + ("%s.%s" % (base_name, suffix))

    def is_alive(self):
        """
        Connectivity check for the current WAMP client (AutobahnWS).
        """

        connected = bool(self.client.is_connected())

        # Add debug logging when connection state changes
        if self._last_alive_state != connected:
            LOG.info("is_alive: state change: %s -> %s", self._last_alive_state, connected)
            pass

        self._last_alive_state = connected

        return connected

    async def connect(self):
        self.state.wamp_ok = False
        self.session_ready = False
        self.service.indicator.blink()
        LOG.info("connect: url=%s realm=%s", self.client.url, self.client.realm)

        gc.collect()

        # Check if we have a pre-resolved host for SNI (Disabled for standard DNS test)
        # server_hostname = self.cfg["wamp"].get("original_host")

        # Set up the on_join callback to handle subscriptions/registrations
        # self.client.on_join(self._on_wamp_join)

        # await self.client.connect()
        # await asyncio.sleep_ms(100)

        try:
            await self.client.connect()
            gc.collect()
            await self._on_wamp_join()  # do setup now, no Event/Flag needed
            gc.collect()

        except Exception as e:
            # make sure we drop sockets/refs so GC can reclaim things
            self.state.last_error = e
            try:
                await self.close()
                gc.collect()
                await asyncio.sleep(5)  # <-- add this
            except Exception:
                pass
            finally:
                gc.collect()
            raise


        self.state.wamp_ok = True
        self.state.last_error = None
        self.service.indicator.on()

    async def _on_wamp_join(self):
        """Called when WAMP session is joined - set up subscriptions and registrations"""
        try:
            await self.client.register(self._topic("control"), self.rpc_control)
            await self.client.register(self._topic("calibrate"), self.rpc_calibrate)
            await self.client.register(self._topic("dose"), self.rpc_dose)
            await self.client.register(self._topic("alert"), self.rpc_alert)
            await self.client.register(self._topic("output"), self.rpc_output)
            await self.client.register(self._topic("status"), self.rpc_status)

            await self.client.register(self._topic("restart"), self.rpc_reboot)

            for suf in self._addr_suffixes():
                await self.client.register(self._addr_topic("calibrate", suf), self.rpc_calibrate)
                await self.client.register(self._addr_topic("dose", suf), self.rpc_dose)
                await self.client.register(self._addr_topic("alert", suf), self.rpc_alert)
                await self.client.register(self._addr_topic("output", suf), self.rpc_output)
                await self.client.register(self._addr_topic("status", suf), self.rpc_status)
                # await self.client.register(self._addr_topic("restart", suf), self.rpc_reboot)
                await self.client.register(self._addr_topic("reset", suf), self.rpc_reset)

            await self.client.subscribe(self._topic("announce.master"), self.on_master)

            await self.publish_announce("announce.online")

            LOG.info("_on_wamp_join: completed")
            self.session_ready = True
            self.service.indicator.on()
            
            # Start keepalive only after session is fully ready
            self.client.start_keepalive()
            
            gc.collect()

        except Exception as e:
            LOG.error("_on_wamp_join: failed %s", e)
            gc.collect()
            self.service.indicator.blink()

            raise

    async def close(self):

        if self.client:
            try:
                await self.client.close()
            except Exception:
                pass

        self.state.wamp_ok = False
        self.session_ready = False
        self.service.indicator.blink()

        # give uasyncio a chance to run socket close callbacks
        await asyncio.sleep_ms(200)
        gc.collect()

    async def publish_announce(self, topic_name, exclude_me=True):

        # LOG.debug("publish_announce: %s", topic_name)

        # require a joined session
        if not self.client.is_connected():
            return

        payload = {"id": self.state.device_id, "ip": self.state.ip,
                   "ver": self.state.version,
                   "build": self.state.build,
                   "ts": time.time(),
                   "config": self.cfg
                   }

        options = {}
        if exclude_me is not None:
            options["exclude_me"] = exclude_me

        pub_id = await self.client.publish(self._topic(topic_name), kwargs=payload, acknowledge=True, options=options)
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
            await asyncio.sleep(0.1)

    async def on_master(self, args, kwargs, details):
        await self.publish_announce("announce.online")

    async def rpc_control(self, args, kwargs, details):

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
        if kwargs.get("type") == "flow" and "calibration" in kwargs:
            cal = int(kwargs["calibration"])
            return self.service.patch_config({"flow": {"calibration": cal}})
        return False

    async def rpc_dose(self, args, kwargs, details):
        """Handle dosing RPC calls"""
        action = kwargs.get("action", "status")

        if action == "start":
            if self.service.stats:
                alert = self.service.stats.get_alert("dosing")
                if alert:
                     return {"error": "alert_active", "reason": alert.get("message"), "ts": alert.get("ts")}
            
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

    async def rpc_alert(self, args, kwargs, details):
        """Handle generic alert management"""
        action = kwargs.get("action", "list")
        
        if action == "list":
             if self.service.stats:
                 return self.service.stats.data.get("alerts", {})
             return {}
             
        elif action == "clear":
             kind = kwargs.get("kind")
             if not kind:
                 return {"error": "missing_kind"}
             self.service.clear_alert(kind)
             return {"status": "cleared", "kind": kind}

        elif action == "set":
             # Mostly for testing or manual overrides
             kind = kwargs.get("kind")
             message = kwargs.get("message", "manual")
             if not kind:
                  return {"error": "missing_kind"}
             self.service.set_alert(kind, message)
             return {"status": "set", "kind": kind}
             
        return {"error": "unknown_action", "action": action}

    async def rpc_output(self, args, kwargs, details):
        """Handle output control RPC calls"""
        name = kwargs.get("name", "pwm")
        duty = kwargs.get("duty", 0.5)
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
        """Get device status including dosing information"""
        return self.service.get_status()

    async def rpc_reset(self, args, kwargs, details):
        return self.service.reset_counters()

    async def rpc_reboot(self, args, kwargs, details):
        t = 1
        if args:
            try:
                t = int(args[0])
            except Exception:
                pass
        if "timeout" in kwargs:
            try:
                t = int(kwargs["timeout"])
            except Exception:
                pass

        return self.service.reboot(t)
