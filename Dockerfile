# Use a smaller base image
ARG IDF_TAG=v5.5.1
ARG BASE_IMAGE=fw_sdk
FROM espressif/idf:${IDF_TAG} AS fw_sdk

ARG MPY_VERSION=1.27.0

ENV MPY_PATH=/micropython

# Clone MicroPython with submodules so `make submodules` can run.
RUN git clone --depth 1 --recurse-submodules --branch "v${MPY_VERSION}" \
    https://github.com/micropython/micropython.git "${MPY_PATH}"



RUN cd $MPY_PATH && make -C mpy-cross
RUN cd /opt/esp/idf && . /opt/esp/idf/export.sh && cd $MPY_PATH/ports/esp32 && make BOARD=ESP32_GENERIC BOARD_VARIANT=OTA

# Set permissions for shared folders
RUN chmod 777 /opt $MPY_PATH

CMD [ "/bin/bash" ]

FROM ${BASE_IMAGE} AS fw_build

WORKDIR ${MPY_PATH}

COPY ./src ${MPY_PATH}/ports/esp32/modules
COPY ./fw_config/ports/esp32 ${MPY_PATH}/ports/esp32

RUN cd /opt/esp/idf && . /opt/esp/idf/export.sh && cd ${MPY_PATH}/ports/esp32/  \
    && make clean \
    && make submodules \
    && make BOARD=ESP32_GENERIC BOARD_VARIANT=OTA && \
    make BOARD=ESP32_GENERIC_S3 BOARD_VARIANT=OTA

VOLUME ["${MPY_PATH}"]

CMD [ "/bin/bash" ]
