"""
Self-test for fixed-point float encoding (4 dp) on ESP32/MicroPython.

Run from REPL after copying the file to the board:
    import umsgpack.test_fixed_4dp

It will raise AssertionError on failure.
"""

import umsgpack


def _check(value):
    buf = umsgpack.dumps(value)
    assert buf[0] not in (0xCA, 0xCB), "float tag present: 0x%02X" % buf[0]
    decoded = umsgpack.loads(buf)
    expected = int(round(value * 10000))
    assert (
        decoded == expected
    ), "mismatch value %r decoded %r expected %r" % (value, decoded, expected)
    print("ok", value, "->", decoded)


def main():
    for v in (0.1, -0.3, 1.2345, 123.0, 0.0001, 0.00009):
        _check(v)
    print("umsgpack fixed 4dp test: PASS")


if __name__ == "__main__":
    main()
