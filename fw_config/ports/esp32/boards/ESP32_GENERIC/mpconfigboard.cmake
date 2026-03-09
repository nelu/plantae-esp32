set(SDKCONFIG_DEFAULTS
    boards/sdkconfig.base
    boards/sdkconfig.no_ble
)

list(APPEND MICROPY_DEF_BOARD
    MICROPY_PY_BLUETOOTH=0
)
