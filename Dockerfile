# Use a smaller base image
ARG IDF_TAG=v5.5.1
ARG BASE_IMAGE=fw_sdk
FROM espressif/idf:${IDF_TAG} AS fw_sdk

ARG MPY_VERSION=1.27.0

ENV MPY_PATH=/micropython

# Download and extract MicroPython archive

RUN mkdir -p /tmp/mpy-src && \
    (command -v curl >/dev/null 2>&1 && \
     curl -L "https://github.com/micropython/micropython/releases/download/v${MPY_VERSION}/micropython-${MPY_VERSION}.tar.xz" -o /tmp/micropython.tar.xz || \
     wget -O /tmp/micropython.tar.xz "https://github.com/micropython/micropython/releases/download/v${MPY_VERSION}/micropython-${MPY_VERSION}.tar.xz") && \
    tar -xJf /tmp/micropython.tar.xz -C /tmp/mpy-src && \
    srcdir="$(find /tmp/mpy-src -maxdepth 1 -type d -name 'micropython*' | head -n 1)" && \
    test -n "$srcdir" && \
    mv "$srcdir" ${MPY_PATH} && \
    rm -rf /tmp/mpy-src /tmp/micropython.tar.xz



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
