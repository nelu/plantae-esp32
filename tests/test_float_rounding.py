"""
Self-test for umsgpack float round-trip tolerance on MicroPython.

Run with:
    import umsgpack.test_float_rounding

Raises AssertionError on failure.
"""

import umsgpack


def _decode_with_tolerance(value, tol):
    buf = umsgpack.dumps(value)
    decoded = umsgpack.loads(buf)
    assert abs(decoded - value) < tol, "decoded %r expected ~%r" % (decoded, value)
    print("ok", value, "->", decoded)


def _check_float(value):
    # Use a tolerance suitable for single precision; double precision will trivially pass it
    _decode_with_tolerance(value, tol=1e-4)


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
    print("umsgpack float tolerance self-test: PASS")


if __name__ == "__main__":
    main()
