import gc
import time

import uasyncio as asyncio

from datetime import unix_now
from logging import LOG

from ..adapters.config_manager import CFG
from mp_wamp_client import MicropythonWampClient  # type: ignore

from ..adapters.device import set_rtc_local_from_utc


def make_name(token, base, device_id):
    return "%s.%s.%s" % (token, base, device_id)


class WampBridge:
    def __init__(self, service):
        self.service = service
        self.session_ready = False
        self.started = False
        self.started_event = asyncio.Event()
        self._last_alive_state = False
        self._wired = False
        self._runner = None

        wamp_cfg = CFG.data.get("wamp", {})
        url = wamp_cfg.get("url")
        realm = wamp_cfg.get("realm", "none")
        token = wamp_cfg.get("token", "")
        mem_logging = bool(wamp_cfg.get("mem_logging", True))
        try:
            auth_fail_retries = int(wamp_cfg.get("auth_fail_retries", 3))
        except Exception:
            auth_fail_retries = 3
        if auth_fail_retries < 1:
            auth_fail_retries = 1

        self._topic_prefix = wamp_cfg.get("prefix", "")
        self._auth_fail_retries = auth_fail_retries
        self._auth_fail_count = 0
        self._auth_recovery_pending = False

        self.client = MicropythonWampClient(
            url=url,
            realm=realm,
            token=token,
            authid="device:"+CFG.device_id,
            reconnect=4,
            max_payload=4096,
            mem_logging=mem_logging,
        )
        # session lifecycle hooks (DeviceApp-style)
        self.client.on_session_join = self._on_session_join  # type: ignore[attr-defined]
        self.client.on_session_lost = self._on_session_lost  # type: ignore[attr-defined]

    def _log_mem_state(self, label):
        if not LOG:
            return
        try:
            free = gc.mem_free()
            alloc = gc.mem_alloc() if hasattr(gc, "mem_alloc") else None
            LOG.info(
                "%s free=%s alloc=%s subs=%d regs=%d pending_subs=%d pending_regs=%d pending_calls=%d runner=%s",
                label,
                free,
                alloc,
                len(self.client._subs_by_id),
                len(self.client._regs_by_id),
                len(self.client._pending_subs),
                len(self.client._pending_regs),
                len(self.client._pending_calls),
                bool(self._runner),
            )
        except Exception:
            pass

    def _schedule_announce(self, topic_name="announce.online"):
        loop = asyncio.get_event_loop()
        loop.create_task(self.publish_announce(topic_name))


    def _name(self, base, no_sufx=False):
        try:
            if self._topic_prefix:
                return no_sufx and "%s.%s" % (self._topic_prefix, base) or make_name(self._topic_prefix, base,
                                                                                self.service.state.device_id)
            else:
                return no_sufx and base or "%s.%s" % (base, self.service.state.device_id)
        except Exception:
            return base

    def _reset_started(self):
        self.started = False
        self.started_event = asyncio.Event()

    @staticmethod
    def _auth_abort_message(details):
        if isinstance(details, dict):
            return details.get("message", "")
        return details and str(details) or ""

    async def start(self, timeout_s=15):
        # Basic gc before connection
        gc.collect()
        self.service.state.wamp_ok = False
        self.session_ready = False
        self._reset_started()

        # Allow reconnect after a previous close that set the client to closing state
        self.client._closing = False

        try:
            self.service.indicator.blink()
        except Exception:
            pass

        if not self._runner or self._runner.done():
            self._runner = asyncio.create_task(self.client.run_forever())

        await self._wait_session_ready(timeout_s)
        await self._wire()
        await self.wait_started()

    def is_alive(self):
        connected = bool(getattr(self.client, "connected", False))

        if self._last_alive_state != connected:
            LOG.info("is_alive: state change: %s -> %s", self._last_alive_state, connected)

        self._last_alive_state = connected
        return connected and self.session_ready

    async def connect(self, timeout_s=15):
        # Backward compatibility: use start()/run_forever
        await self.start(timeout_s=timeout_s)

    async def _wait_session_ready(self, timeout_s):
        t0 = time.ticks_ms()
        while not self.session_ready:
            await asyncio.sleep_ms(50)
            if self._runner and self._runner.done():
                raise OSError("WAMP session ready timeout (join failed)")
            if getattr(self.client, "_closing", False):
                raise OSError("WAMP session ready timeout (join failed)")
            if time.ticks_diff(time.ticks_ms(), t0) > int(timeout_s * 1000):
                raise OSError("WAMP session ready timeout (join failed)")

    async def _wire(self):
        if self._wired:
            return
        # Broad master subscription (no device suffix) for pool discovery
        await self.client.subscribe(self._name("announce.master", no_sufx=True), self.on_master)
        await self.client.register(self._name("control"), self.rpc_control)
        await self.client.register(self._name("calibrate"), self.rpc_calibrate)
        await self.client.register(self._name("dose"), self.rpc_dose)
        await self.client.register(self._name("alert"), self.rpc_alert)
        await self.client.register(self._name("output"), self.rpc_output)
        await self.client.register(self._name("status"), self.rpc_status)
        await self.client.register(self._name("restart"), self.rpc_reboot)
        await self.client.register(self._name("reset"), self.rpc_reset)

        if self.client.realm == "none":
            pass
            # await self.client.register(self._name("hwpair"), self.rpc_hwpair)



        self._wired = True

    def _on_session_join(self, session_id=None, session_data=None):

        if session_data:
            auth_info = session_data.get('authextra', {})
            user_id = auth_info.get('user_id')
            tz_data = auth_info.get('device_tz')
            if tz_data:
                set_rtc_local_from_utc(auth_info.get('utc_time'), tz_data)
                if tz_data != CFG.data['tz_offset_min']:
                    CFG.update({'tz_offset_min': tz_data})
                    CFG.save()
            if user_id:
                self._topic_prefix = user_id

        LOG.info("session joined: %s %s", session_id, session_data)

        self._auth_fail_count = 0
        self._auth_recovery_pending = False
        self.session_ready = True
        self.service.state.wamp_ok = True
        self.service.state.last_error = None
        self.started = True



        self.started_event.set()
        self.service.indicator.on()
        self._schedule_announce("announce.online")
        self._log_mem_state("wamp_bridge: session_join")

    def _on_session_lost(self):
        reason = getattr(self.client, "last_abort_reason", None)
        details = getattr(self.client, "last_abort_details", None)

        if reason == "wamp.error.authentication_failed":
            self._auth_fail_count += 1
            auth_msg = self._auth_abort_message(details)
            self.service.state.last_error = auth_msg or "wamp authentication failed"
            if auth_msg:
                LOG.error("wamp auth failed (%d/%d): %s", self._auth_fail_count, self._auth_fail_retries, auth_msg)
            else:
                LOG.error("wamp auth failed (%d/%d)", self._auth_fail_count, self._auth_fail_retries)

            if not self._auth_recovery_pending and self._auth_fail_count >= self._auth_fail_retries:
                self._auth_recovery_pending = True
                LOG.error("wamp auth retries exhausted; resetting wamp config and rebooting")
                try:
                    CFG.update({"wamp": {"realm": "none", "prefix": "", "token": ""}})
                    CFG.save()
                    self.client.realm = "none"
                    self.client.token = ""
                    self._topic_prefix = ""
                except Exception as exc:
                    LOG.error("wamp auth recovery save failed: %s", exc)
                try:
                    self.service.reboot(2)
                except Exception as exc:
                    LOG.error("wamp auth recovery reboot failed: %s", exc)
        else:
            if self._auth_fail_count:
                LOG.info("wamp auth fail counter reset")
            self._auth_fail_count = 0
            self._auth_recovery_pending = False

        LOG.info("session lost")
        self.session_ready = False
        self.service.state.wamp_ok = False
        self._reset_started()
        try:
            self.service.indicator.blink()
        except Exception:
            pass
        self._log_mem_state("wamp_bridge: session_lost")

    async def close(self):
        # Close the client first so run_forever() exits cleanly
        await self.client.close()

        # Cancel runner task if still present
        if self._runner:
            self._runner.cancel()
            try:
                await self._runner
            except asyncio.CancelledError:
                pass
            finally:
                self._runner = None

        self.service.state.wamp_ok = False
        self.session_ready = False
        self._reset_started()
        self.service.indicator.blink()

        self._log_mem_state("wamp_bridge: close")

        await asyncio.sleep_ms(200)
        gc.collect()

    async def publish_announce(self, topic_name, exclude_me=True):
        if not self.is_alive():
            return

        payload = {
            "id": self.service.state.device_id,
            "ip": self.service.state.ip,
            "ver": self.service.state.version,
            "build": self.service.state.build,
            "ts": unix_now(),
            "config": CFG.data,
            "alerts": self.service.state.alerts.data
        }

        options = {}
        if exclude_me is not None:
            options["exclude_me"] = exclude_me

        # Broad announce only (pool discovery; no device suffix)
        await self.client.publish(self._name(topic_name, no_sufx=True), kwargs=payload, options=options)

    async def publish_activity(self, payload):
        if not self.is_alive():
            return
        await self.client.publish(self._name("activity"), kwargs=payload)

    async def publish_switch(self, idx, on):
        if not self.is_alive():
            return
        await self.client.publish(self._name("switch"), args=[int(idx), int(bool(on))])

    async def publish_alerts(self):
        if not self.is_alive():
            return
        await self.publish_topic("alerts", {"alerts": self.service.state.alerts.data})

    async def publish_topic(self, topic, payload, options=None):
        if not self.is_alive():
            return
        await self.client.publish(self._name(topic), kwargs=payload, options=options or {})

    # async def get_device_config(self):
    #     if not self.is_alive():
    #         return
    #
    #     await self.client.call("plantae.backend.get_config", kwargs={"device_id": CFG.device_id}, on_result=rtc_via_wamp)

    async def publish_status(self, **kwargs):
        if not self.is_alive():
            return
        await self.client.publish(self._name("status"), kwargs=self.service.state.snapshot())
        await asyncio.sleep(0.1)

    def is_started(self):
        return self.started

    async def wait_started(self):
        await self.started_event.wait()
        return self.started

    async def on_master(self, args, kwargs):
        LOG.debug("on_master: received announce.master -> announce.online")
        self._schedule_announce("announce.online")

    async def rpc_control(self, args, kwargs):

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

        if "update" in kwargs and isinstance(kwargs["update"], str):
            return self.service.update_firmware(kwargs["update"].strip())

        return False

    async def rpc_calibrate(self, args, kwargs):
        if kwargs.get("type") == "flow" and "calibration" in kwargs:
            cal = int(kwargs["calibration"])
            return self.service.patch_config({"flow": {"calibration": cal}})
        return False

    async def rpc_dose(self, args, kwargs):
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
            self.service.dosing.reset_last_auto_dose_day()
            return {"status": "updated"}

        elif action == "stop":
            success = self.service.dosing.stop_dose()
            return {"status": "stopped" if success else "not_active"}

        elif action == "status":
            return self.service.dosing.get_dose_status()

        else:
            return {"error": "unknown_action", "action": action}

    async def rpc_alert(self, args, kwargs):
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

    async def rpc_output(self, args, kwargs):
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

    async def rpc_status(self, args, kwargs):
        """Get device status including dosing information"""
        try:
            return self.service.get_status()
        except Exception as exc:
            return {"error": str(exc)}

    async def rpc_reset(self, args, kwargs):
        return self.service.reset_counters()

    async def rpc_hwpair(self, args, kwargs):
        while True:
            if self.service.state.hwpairing:
                await self.rpc_control([], {"patch_cfg": kwargs.get("patch_cfg", {})})
            await asyncio.sleep_ms(100)

    async def rpc_reboot(self, args, kwargs):
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
