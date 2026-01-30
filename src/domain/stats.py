import time

from lib.file_store import load_with_default, atomic_save


DEFAULT_STATS = {
    "last_dose_ts": 0,
    "lifetime_volume_l": 0.0,
    "pwm_runtime_s": 0.0,
    "alerts": {},
}


def _merge_stats(dst, src):
    for k, v in src.items():
        if k in DEFAULT_STATS:
            if k == "alerts" and isinstance(v, dict):
                # Deep merge alerts to preserve existing
                if "alerts" not in dst:
                    dst["alerts"] = {}
                for ak, av in v.items():
                    dst["alerts"][ak] = av
            else:
                dst[k] = v


class StatsManager:
    def __init__(self, path="stats.mpk", save_interval_s=60):
        self.path = path
        self.save_interval_ms = int(save_interval_s * 1000)
        self.data = dict(DEFAULT_STATS)
        # Ensure ID for alerts dict to reduce fragmentation
        if "alerts" not in self.data:
            self.data["alerts"] = {}
            
        self.dirty = False
        self._last_save_ms = time.ticks_ms()
        self._last_volume_l = None
        self._last_pwm_sample_ms = time.ticks_ms()
        self.state = None

    def _default(self):
        base = dict(DEFAULT_STATS)
        if "alerts" not in base:
            base["alerts"] = {}
        return base

    def attach_state(self, state):
        self.state = state
        if state:
            state.last_dose_ts = int(self.data.get("last_dose_ts", 0) or 0)
            state.lifetime_volume_l = float(self.data.get("lifetime_volume_l", 0.0) or 0.0)
            state.pwm_runtime_s = float(self.data.get("pwm_runtime_s", 0.0) or 0.0)
            # Bind the alerts dictionary reference directly
            state.alerts = self.data.get("alerts", {})
            self._last_volume_l = getattr(state, "volume_l", 0.0)

    def load(self):
        loaded = load_with_default(self.path, self._default)

        saved = False
        try:
            if loaded.get("dosing_alert") is True:
                reason = loaded.get("dosing_alert_reason", "timeout")
                ts = loaded.get("dosing_alert_ts", 0)
                alerts = loaded.get("alerts") or {}
                alerts["dosing"] = {"message": reason, "ts": ts}
                loaded["alerts"] = alerts
                try:
                    del loaded["dosing_alert"]
                    del loaded["dosing_alert_reason"]
                    del loaded["dosing_alert_ts"]
                except Exception:
                    pass
                saved = True
        except Exception:
            pass

        base = self._default()
        _merge_stats(base, loaded)
        self.data = base

        if saved:
            self.save()

        self.dirty = False
        import gc
        gc.collect()
        return self.data

    def _mark_dirty(self):
        self.dirty = True

    def save(self):
        atomic_save(self.path, self.data)
        self._last_save_ms = time.ticks_ms()
        self.dirty = False
        import gc
        gc.collect()

    def save_if_needed(self, force=False):
        now = time.ticks_ms()
        if force or (self.dirty and time.ticks_diff(now, self._last_save_ms) >= self.save_interval_ms):
            self.save()

    def record_dose(self, ts=None, persist_immediately=False):
        ts = int(ts if ts is not None else time.time())
        self.data["last_dose_ts"] = ts
        if self.state:
            self.state.last_dose_ts = ts
        self._mark_dirty()
        if persist_immediately:
            self.save_if_needed(force=True)

    def last_dose_day(self):
        ts = int(self.data.get("last_dose_ts") or 0)
        if ts <= 0:
            return -1
        return ts // 86400

    def accumulate_volume(self, current_volume_l):
        if self._last_volume_l is None:
            self._last_volume_l = float(current_volume_l)
            return
        delta = float(current_volume_l) - float(self._last_volume_l)
        if delta > 0:
            self.data["lifetime_volume_l"] = float(self.data.get("lifetime_volume_l", 0.0)) + delta
            if self.state:
                self.state.lifetime_volume_l = self.data["lifetime_volume_l"]
            self._mark_dirty()
        self._last_volume_l = float(current_volume_l)

    def track_pwm_runtime(self, duty, now_ms=None):
        if now_ms is None:
            now_ms = time.ticks_ms()
        if self._last_pwm_sample_ms is None:
            self._last_pwm_sample_ms = now_ms
            return
        dt = time.ticks_diff(now_ms, self._last_pwm_sample_ms)
        self._last_pwm_sample_ms = now_ms
        if dt > 0 and duty and duty > 0:
            self.data["pwm_runtime_s"] = float(self.data.get("pwm_runtime_s", 0.0)) + (dt / 1000.0)
            if self.state:
                self.state.pwm_runtime_s = self.data["pwm_runtime_s"]
            self._mark_dirty()

    def set_alert(self, kind, message, ts=None, persist=False):
        """Generic alert setter. Reuses dict components to reduce fragmentation."""
        ts_val = int(ts if ts is not None else time.time())
        alerts = self.data.get("alerts")
        if alerts is None:
            alerts = {}
            self.data["alerts"] = alerts
            if self.state:
                self.state.alerts = alerts

        # Reuse existing dictionary if present
        if kind in alerts:
            alert = alerts[kind]
            alert["message"] = message
            alert["ts"] = ts_val
        else:
            alerts[kind] = {"message": message, "ts": ts_val}
            
        self._mark_dirty()
        if persist:
            self.save_if_needed(force=True)

    def clear_alert(self, kind, persist=False):
        alerts = self.data.get("alerts")
        if alerts and kind in alerts:
            del alerts[kind]
            self._mark_dirty()
            if persist:
                self.save_if_needed(force=True)
            return True
        return False

    def get_alert(self, kind):
        return self.data.get("alerts", {}).get(kind)
