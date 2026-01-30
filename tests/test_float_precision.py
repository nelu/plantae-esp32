"""
Self-test for umsgpack float precision on MicroPython/ESP32.

Run with:
    import umsgpack.test_float_precision  # in the board REPL
or
    import src.lib.umsgpack.test_float_precision  # if using CPython pathing

Fails fast with AssertionError if expectations are not met.
"""

import struct
import umsgpack


def _check_default_precision():
    expected = "double" if struct.calcsize("d") == 8 else "single"
    assert (
        umsgpack.float_precision == expected
    ), "float_precision=%s expected %s" % (umsgpack.float_precision, expected)
    print("default precision:", umsgpack.float_precision)


def _check_tag_and_roundtrip(val):
    buf = umsgpack.dumps(val)
    tag = buf[0]
    assert tag in (0xCA, 0xCB), "unexpected float tag: 0x%02X" % tag
    decoded = umsgpack.loads(buf)
    tol = 1e-9 if tag == 0xCB else 1e-4
    assert abs(val - decoded) < tol, "roundtrip drift %r -> %r" % (val, decoded)
    print("value", val, "tag", hex(tag), "decoded", decoded)


def _check_ints_stay_ints():
    buf = umsgpack.dumps(123)
    assert buf[0] not in (0xCA, 0xCB), "int encoded as float"
    assert umsgpack.loads(buf) == 123
    print("integer encoding OK")


def main():
    _check_default_precision()
    for val in (0.1, 1.1, -0.3, 123456.789):
        _check_tag_and_roundtrip(val)
    _check_ints_stay_ints()
    print("umsgpack float precision self-test: PASS")


if __name__ == "__main__":
    main()
