"""
Self-test for default float rounding (4 dp) in umsgpack.

Run with:
    import umsgpack.test_float_rounding

Raises AssertionError on failure.
"""

import umsgpack


def _fmt(val):
    digits = umsgpack.float_round_digits
    return ("{0:." + str(digits) + "f}").format(val)


def _check_float(value):
    buf = umsgpack.dumps(value)
    decoded = umsgpack.loads(buf)
    expected = round(value, umsgpack.float_round_digits)
    assert _fmt(decoded) == _fmt(expected), "decoded %r expected %r" % (decoded, expected)
    print("ok", value, "->", decoded)


def _check_int(value):
    buf = umsgpack.dumps(value)
    decoded = umsgpack.loads(buf)
    assert isinstance(decoded, int) and decoded == value
    print("int ok", value)


def main():
    for v in (0.1, -0.3, 1.234567, 123.00009, 100.00000149):
        _check_float(v)
    for i in (0, 1, 42, -7):
        _check_int(i)
    print("umsgpack float rounding self-test: PASS")


if __name__ == "__main__":
    main()
