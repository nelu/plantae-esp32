import os
import time
import gc

from datetime import unix_now
from logging import LOG


def merge(dst, src):
    for k, v in src.items():
        if isinstance(v, dict):
            if not isinstance(dst.get(k), dict):
                dst[k] = {}
            merge(dst[k], v)
        elif isinstance(v, list):
            dst[k] = list(v)
        else:
            dst[k] = v


def load_with_default(path, default_fn):
    data = default_fn()
    try:
        with open(path, "rb") as f:
            import umsgpack

            stored = umsgpack.load(f)
        if isinstance(stored, dict):
            merge(data, stored)
    except Exception as e:
        try:
            LOG.warning("file_store: load failed for %s: %s", path, e)
        except Exception:
            pass
    return data


def atomic_save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        import umsgpack

        umsgpack.dump(data, f)
    try:
        os.remove(path)
    except Exception:
        pass
    os.rename(tmp, path)


class PersistentManager:
    """Small helper to persist manager state with dirty tracking."""

    def __init__(self, path, save_interval_s=60, initial=None, default_factory=None):
        self.path = path
        self.save_interval_ms = int(save_interval_s * 1000)
        self.default_factory = default_factory or (lambda: {})

        self.data = initial if isinstance(initial, dict) else self.default_factory()
        self.dirty = False
        self._loaded = False
        self._last_save_ms = time.ticks_ms()
        self.epoch_offset = 0

    def default(self):
        return self.default_factory()

    def _normalize_ts(self, ts):
        try:
            ts_val = int(ts)
        except Exception:
            return 0
        if ts_val <= 0:
            return 0
        if ts_val < self.epoch_offset:
            return ts_val + self.epoch_offset
        return ts_val

    def _now_unix(self):
        return unix_now()

    def _mark_dirty(self):
        self.dirty = True

    def _load_with_default(self):
        loaded = load_with_default(self.path, self.default)
        return loaded if isinstance(loaded, dict) else self.default()

    def load(self):
        self.data = self._load_with_default()
        self.dirty = False
        self._loaded = True
        gc.collect()
        return self.data

    def save(self):
        atomic_save(self.path, self.data)
        self._last_save_ms = time.ticks_ms()
        self.dirty = False
        gc.collect()

    def save_if_needed(self, force=False):
        now = time.ticks_ms()
        if force or (self.dirty and time.ticks_diff(now, self._last_save_ms) >= self.save_interval_ms):
            self.save()
