MicroPython test commands (unix v1.27.0)
=======================================

Use the MicroPython unix image to run the self-tests that target the bundled
`umsgpack` and scheduler logic.

Set MICROPYPATH so project modules and the optional `lib/` directory are found:

```sh
MICROPY_CMD="docker run --rm -v \"%cd%\":/app -w /app -e MICROPYPATH=/app:/app/lib:/app/src/lib:/app/src micropython/unix:v1.27.0 micropython"
```

Install unittest into the working tree (once per clean tree) so MicroPython can import it:

```sh
docker run --rm -v "%cd%":/app -w /app micropython/unix:v1.27.0 micropython -c "import mip; mip.install('unittest', target='/app/lib')"
```

Run the tests:

```sh
$MICROPY_CMD tests/test_float_precision.py
$MICROPY_CMD tests/test_float_rounding.py
$MICROPY_CMD tests/test_fixed_4dp.py   # prints SKIPPED (not implemented)
$MICROPY_CMD tests/unit/test_scheduler.py
```

Notes
- The fixed 4dp test is intentionally skipped because the bundled `umsgpack` does not implement fixed-point float encoding.
- Running `micropython -m unittest` is unnecessary; execute the test files directly with the MICROPYPATH above.
