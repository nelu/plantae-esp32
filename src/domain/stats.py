import time

from domain.state import DeviceState
from lib.file_store import PersistentManager


class StatsManager(PersistentManager):
    def __init__(self, path="stats.mpk", save_interval_s=60):
        super().__init__(path, save_interval_s, default_factory=self.default)

        self._last_volume_l = None
        self._last_pwm_sample_ms = time.ticks_ms()
        self.epoch_offset = DeviceState.UNIX_EPOCH_OFFSET

    def default(self):
        return {
            "last_dose_ts": 0,
            "lifetime_volume_l": 0.0,
            "pwm_runtime_s": 0.0,
        }

    def _merge_stats(self, dst, src):
        allowed = self.default()
        for k, v in src.items():
            if k not in allowed:
                continue
            dst[k] = v

    def attach_state(self, state):
        # Deprecated: state binding removed; only track last volume for delta calculations when provided
        self._last_volume_l = getattr(state, "volume_l", 0.0) if state else None

    def load(self):
        loaded = self._load_with_default()

        base = self.default()
        self._merge_stats(base, loaded)
        base["last_dose_ts"] = self._normalize_ts(base.get("last_dose_ts", 0))
        self.data = base

        self.dirty = False
        self._loaded = True
        import gc
        gc.collect()
        return self.data

    def record_dose(self, ts=None, persist_immediately=False):
        ts_norm = self._now_unix() if ts is None else self._normalize_ts(ts)
        self.data["last_dose_ts"] = ts_norm
        self._mark_dirty()
        if persist_immediately:
            self.save_if_needed(force=True)

    def last_dose_day(self):
        ts = self._normalize_ts(self.data.get("last_dose_ts") or 0)
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
            self._mark_dirty()
