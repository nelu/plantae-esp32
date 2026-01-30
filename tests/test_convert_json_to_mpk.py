"""
Utility script to convert legacy JSON config/stats to msgpack (.mpk).
Run on host: `python tests/test_convert_json_to_mpk.py`
"""

import json
import os

import umsgpack


def convert(src, dst):
    if not os.path.exists(src):
        print(f"skip: {src} not found")
        return
    try:
        with open(src, "r") as f:
            data = json.load(f)
        with open(dst, "wb") as f:
            umsgpack.dump(data, f)
        print(f"ok: {src} -> {dst}")
    except Exception as e:
        print(f"error: {src} -> {dst}: {e}")


if __name__ == "__main__":
    convert("config.json", "config.mpk")
    convert("stats.json", "stats.mpk")
