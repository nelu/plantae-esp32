# Use a smaller base image
ARG IDF_TAG=v5.5.1
ARG BASE_IMAGE=fw_sdk
ARG app_version=latest
FROM espressif/idf:${IDF_TAG} AS fw_sdk

ARG app_version
ENV APP_VERSION=${app_version}

ARG MPY_VERSION=1.27.0

ENV MPY_PATH=/micropython

# Clone MicroPython with submodules so `make submodules` can run.
RUN git clone --depth 1 --recurse-submodules --branch "v${MPY_VERSION}" \
    https://github.com/micropython/micropython.git "${MPY_PATH}"

#RUN mkdir -p /tmp/mpy-src && \
#    (command -v curl >/dev/null 2>&1 && \
#     curl -L "https://github.com/micropython/micropython/releases/download/v${MPY_VERSION}/micropython-${MPY_VERSION}.tar.xz" -o /tmp/micropython.tar.xz || \
#     wget -O /tmp/micropython.tar.xz "https://github.com/micropython/micropython/releases/download/v${MPY_VERSION}/micropython-${MPY_VERSION}.tar.xz") && \
#    tar -xJf /tmp/micropython.tar.xz -C /tmp/mpy-src && \
#    srcdir="$(find /tmp/mpy-src -maxdepth 1 -type d -name 'micropython*' | head -n 1)" && \
#    test -n "$srcdir" && \
#    mv "$srcdir" ${MPY_PATH} && \
#    rm -rf /tmp/mpy-src /tmp/micropython.tar.xz


RUN cd $MPY_PATH && make -C mpy-cross
COPY ./fw_config/ports/esp32 ${MPY_PATH}/ports/esp32

RUN cd /opt/esp/idf && . /opt/esp/idf/export.sh && cd $MPY_PATH/ports/esp32 \
    && make BOARD=ESP32_GENERIC BOARD_VARIANT=OTANOBLE && \
    make BOARD=ESP32_GENERIC_S3 BOARD_VARIANT=OTA

# Set permissions for shared folders
RUN chmod 777 /opt $MPY_PATH

CMD [ "/bin/bash" ]

FROM ${BASE_IMAGE} AS fw_build

ARG app_version
ENV APP_VERSION=${app_version}

WORKDIR ${MPY_PATH}

COPY ./src ${MPY_PATH}/ports/esp32/modules
COPY ./fw_config/ports/esp32 ${MPY_PATH}/ports/esp32


RUN cd /opt/esp/idf && . /opt/esp/idf/export.sh && cd ${MPY_PATH}/ports/esp32/  \
#    && make submodules \
    && make BOARD=ESP32_GENERIC BOARD_VARIANT=OTANOBLE \
    && python gen_ota.py build-ESP32_GENERIC-OTANOBLE plantae-esp32-micropython-ota.bin plantae-flash.tar.gz \
    && make BOARD=ESP32_GENERIC_S3 BOARD_VARIANT=OTA \
    && python gen_ota.py build-ESP32_GENERIC_S3-OTA plantae-esp32s3-micropython-ota.bin plantae-flash.tar.gz

COPY ./build /tmp/build
RUN chmod -R 775 /tmp/build && /tmp/build/version.sh "${MPY_PATH}/ports/esp32/modules/plantae/version.py" \
    && /tmp/build/compile.sh "${MPY_PATH}/ports/esp32/modules/plantae" "/plantae" \
    && rm -rf "${MPY_PATH}/ports/esp32/modules/plantae" \
    && tar -czf "${MPY_PATH}/ports/esp32/plantae-flash.tar.gz" -C /plantae

VOLUME ["${MPY_PATH}"]

CMD [ "/bin/bash" ]
