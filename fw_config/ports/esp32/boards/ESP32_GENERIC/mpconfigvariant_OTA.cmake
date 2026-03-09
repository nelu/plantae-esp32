set(SDKCONFIG_DEFAULTS
    ${SDKCONFIG_DEFAULTS}
    boards/ESP32_GENERIC/sdkconfig.ota
    boards/sdkconfig.no_ble
)

list(APPEND MICROPY_DEF_BOARD
    MICROPY_HW_BOARD_NAME="Plantae ESP32 module with OTA noBLE"
)
