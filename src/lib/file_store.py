import os
from lib.logging import LOG


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
