#!/bin/bash

# Configuration
MPY_CROSS="${3:-"mpy\-cross"}"
SRC_DIR="${1:-src}"
DIST_DIR="${2:-dist}"

#./version.sh src/version.py

echo "$(date '+%Y-%m-%d %H:%M:%S') Building Production Image in $DIST_DIR..."

# 1. Clean/Create Dist
rm -rf "$DIST_DIR"
mkdir -p "$DIST_DIR"

# 2. Copy Assets (main.py, etc)
#ASSETS=("provision.html")
ASSETS=("boot.py" "main.py" "provision.html")
for asset in "${ASSETS[@]}"; do
    if [ -f "$SRC_DIR/$asset" ]; then
        cp "$SRC_DIR/$asset" "$DIST_DIR/$asset"
        echo "$(date '+%Y-%m-%d %H:%M:%S') Copied $asset"
    fi
done

# 3. Files to Compile
FILES=(
    "plantae/__init__.py"

#    "protocols/mpautobahn/__init__.py"
#    "protocols/mpautobahn/client.py"
#    "protocols/mpautobahn/constants.py"

    "plantae/adapters/config_manager.py"
    "plantae/adapters/device.py"
    "plantae/adapters/http_api.py"
    "plantae/adapters/wamp_bridge.py"
    "plantae/adapters/wifi.py"

    "plantae/app/bootstrap.py"
    "plantae/app/provision.py"
    "plantae/app/supervisor.py"
    "plantae/app/tasks.py"

    "plantae/domain/controllers.py"
    "plantae/domain/device_service.py"
    "plantae/domain/dosing.py"
    "plantae/domain/scheduler.py"
    "plantae/domain/state.py"
    "plantae/domain/stats.py"

    "plantae/drivers/pca9685.py"
    "plantae/drivers/pwm_out.py"
    "plantae/drivers/flowsensor.py"

    "plantae/version.py"

#    "lib/datetime.py"
#    "lib/file_store.py"
#    "lib/mp_wamp_client.py"
#    "lib/logging.py"
#    "lib/async_websocket_client/__init__.py"
#    "lib/async_websocket_client/ws.py"

#    "lib/umsgpack/__init__.py"
#    "lib/umsgpack/mp_dump.py"
#    "lib/umsgpack/mp_load.py"
#    "lib/umsgpack/mpk_bytearray.py"
#    "lib/umsgpack/mpk_tuple.py"
#    "lib/umsgpack/mpk_set.py"
#    "lib/umsgpack/mpk_odict.py"
#    "lib/umsgpack/mpk_complex.py"
#    "lib/umsgpack/as_loader.py"


)

for rel_file in "${FILES[@]}"; do
    src_path="$SRC_DIR/$rel_file"

    if [ -f "$src_path" ]; then
        # Create subdir in dist
        rel_dir=$(dirname "$rel_file")
        mkdir -p "$DIST_DIR/$rel_dir"

        # Output path (.mpy)
        filename=$(basename "$rel_file" .py)
        out_path="$DIST_DIR/$rel_dir/$filename.mpy"

        echo "$(date '+%Y-%m-%d %H:%M:%S') Compiling $rel_file -> $out_path"
#        $MPY_CROSS -O3 -s "$rel_file" -o "$out_path" -- "$src_path"
        $MPY_CROSS -o "$out_path" -- "$src_path"

        if [ $? -ne 0 ]; then
            echo "$(date '+%Y-%m-%d %H:%M:%S')  [FAIL]"
            exit 1
        fi
    else
        echo "$(date '+%Y-%m-%d %H:%M:%S') Skipping missing: $src_path"
    fi
done

echo "$(date '+%Y-%m-%d %H:%M:%S') Build Complete. Directory: $DIST_DIR"
