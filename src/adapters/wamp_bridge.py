import gc
import time

import uasyncio as asyncio

from lib.logging import LOG
from protocols.mpautobahn import AutobahnWS


class WampBridge:
    def __init__(self, cfg, service):
        self.cfg = cfg
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

    def _topic(self, name):
        return self.cfg["wamp"].get("prefix", "") + "." + name

    def _device_topic(self, topic_name, suffix=None):
        suffix = suffix or self.service.state.device_id
        return self._topic(topic_name + "." + suffix)

    def is_alive(self):
        """
        Connectivity check for the current WAMP client (AutobahnWS).
        """

        connected = bool(self.client.is_connected())

        # Add debug logging when connection state changes
        if self._last_alive_state != connected:
            LOG.info("is_alive: state change: %s -> %s", self._last_alive_state, connected)
            if not connected:
                self.close()

        self._last_alive_state = connected

        return connected and self.session_ready

    async def connect(self, timeout_s=15):
        self.service.state.wamp_ok = False
        self.session_ready = False
        self.service.indicator.blink()
        LOG.info("connect: url=%s realm=%s", self.client.url, self.client.realm)

        try:
            self.client.on_join(self._on_wamp_join)
            gc.collect()
            await self.client.connect()

        except Exception as e:
            # make sure we drop sockets/refs so GC can reclaim things
            self.service.state.last_error = e
            try:
                await self.close()
                gc.collect()
                await asyncio.sleep(5)  # <-- add this
            except Exception:
                pass
            finally:
                gc.collect()
            raise

        t0 = time.ticks_ms()

        while not self.session_ready:
            await asyncio.sleep_ms(50)
            if time.ticks_diff(time.ticks_ms(), t0) > int(timeout_s * 1000):
                raise OSError("WAMP session ready timeout (on_join failed)")

    async def _on_wamp_join(self, session_id=None):
        """Called when WAMP session is joined - set up subscriptions and registrations"""
        LOG.info("_on_wamp_join: start %s", session_id)

        try:
            await self.client.register(self._device_topic("control"), self.rpc_calibrate)
            await self.client.register(self._device_topic("calibrate"), self.rpc_calibrate)
            await self.client.register(self._device_topic("dose"), self.rpc_dose)
            await self.client.register(self._device_topic("alert"), self.rpc_alert)
            await self.client.register(self._device_topic("output"), self.rpc_output)
            await self.client.register(self._device_topic("status"), self.rpc_status)
            await self.client.register(self._device_topic("restart"), self.rpc_reboot)
            await self.client.register(self._device_topic("reset"), self.rpc_reset)

            await self.client.subscribe(self._topic("announce.master"), self.on_master)

            await self.publish_announce("announce.online")

            LOG.info("_on_wamp_join: completed session=%s", session_id)

            self.session_ready = True
            self.service.state.wamp_ok = True
            self.service.state.last_error = None
            self.service.indicator.on()
            # Start keepalive only after session is fully ready
            # self.client.start_keepalive()

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

        self.service.state.wamp_ok = False
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
        LOG.info("publish_announce: connect. Free: %d",  gc.mem_free())

        payload = {"id": self.service.state.device_id,
                   "ip": self.service.state.ip,
                   "ver": self.service.state.version,
                   "build": self.service.state.build,
                   "ts": time.time(),
                   "config": self.cfg
                   }

        options = {}
        if exclude_me is not None:
            options["exclude_me"] = exclude_me

        options["acknowledge"] = False
        gc.collect()
        LOG.info("publish_announce: connect. Free: %d",  gc.mem_free())

        pub_id = await self.client.publish(self._topic(topic_name), kwargs=payload, options=options)
        gc.collect()

        # LOG.debug("Announce published: %s pub_id=%s", topic_name, pub_id)

    async def publish_activity(self, payload):
        if not self.is_alive(): return
        await self.publish_device_topic("activity", payload=payload)

    async def publish_switch(self, idx, on):
        if not self.client: return
        await self.client.publish(self._topic("switch"), args=[int(idx), int(bool(on))])

    async def publish_topic(self, topic, payload, options=None):
        if not self.is_alive(): return
        await self.client.publish(self._topic(topic), kwargs=payload, options=options)

    async def publish_device_topic(self, topic, payload):
        if not self.is_alive(): return
        await self.client.publish(self._device_topic(topic), kwargs=payload)

    async def publish_status(self, **kwargs):
        # LOG.debug("publish_status")
        if not self.is_alive(): return
        await self.publish_device_topic("status", payload=self.service.state.snapshot())
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
            quantity = kwargs.get("quantity", 0.0)
            if quantity <= 0:
                return {"error": "invalid_quantity", "quantity": quantity}

            success = await self.service.dosing.start_dose(quantity, is_manual=True)
            if success:
                return {"status": "started", "quantity": quantity}
            else:
                return {"error": "failed_to_start"}

        elif action == "set_schedule":
            dosing_cfg = kwargs.get("dosing") or kwargs.get("schedule") or {}
            if not isinstance(dosing_cfg, dict):
                return {"error": "invalid_payload", "reason": "dosing config must be dict"}

            new_cfg = {}

            if "days" not in dosing_cfg:
                return {"error": "missing_field", "required": ["days"]}

            days = dosing_cfg.get("days")
            if not isinstance(days, list) or len(days) != 7:
                return {"error": "invalid_field", "field": "days", "reason": "must_be_list_len_7"}

            parsed_days = []
            for idx, entry in enumerate(days):
                if entry in (None, "", False):
                    parsed_days.append("")
                    continue
                s = str(entry)
                if ":" not in s:
                    return {"error": "invalid_time", "day_index": idx}
                parsed_days.append(s)

            new_cfg["days"] = parsed_days

            if "quantity" in dosing_cfg:
                try:
                    qty = float(dosing_cfg.get("quantity", 0))
                except Exception:
                    return {"error": "invalid_field", "field": "quantity"}
                if qty < 0:
                    return {"error": "invalid_field", "field": "quantity"}
                new_cfg["quantity"] = qty

            self.service.patch_config({"schedule": {"dosing": new_cfg}})
            return {"status": "updated"}

        elif action == "stop":
            success = self.service.dosing.stop_dose()
            return {"status": "stopped" if success else "not_active"}

        elif action == "status":
            return self.service.dosing.get_dose_status()

        else:
            return {"error": "unknown_action", "action": action}

    async def rpc_alert(self, args, kwargs, details):
        """Handle generic alert management"""
        action = kwargs.get("action", "list")

        if action == "list":
            return self.service.state.alerts.all()

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
