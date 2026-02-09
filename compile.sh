#!/bin/bash

# Configuration
MPY_CROSS="mpy-cross"
SRC_DIR="src"
DIST_DIR="dist"

TODAY=$(date '+%Y-%m-%d')
VERSION_FILE="${SRC_DIR}/version.py"

if [ -f "$VERSION_FILE" ]; then
    tmp_file=$(mktemp)
    if sed -E "s/^BUILD_DATE\s*=\s*\".*\"/BUILD_DATE = \"${TODAY}\"/" "$VERSION_FILE" >"$tmp_file"; then
        mv "$tmp_file" "$VERSION_FILE"
        echo "$(date '+%Y-%m-%d %H:%M:%S') Updated BUILD_DATE in $VERSION_FILE to ${TODAY}"
    else
        rm -f "$tmp_file"
        echo "$(date '+%Y-%m-%d %H:%M:%S') Failed updating BUILD_DATE in $VERSION_FILE" >&2
        exit 1
    fi
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') Missing $VERSION_FILE" >&2
    exit 1
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') Building Production Image in $DIST_DIR..."

# 1. Clean/Create Dist
rm -rf "$DIST_DIR"
mkdir -p "$DIST_DIR"

# 2. Copy Assets (main.py, etc)
ASSETS=("boot.py" "main.py" "provision.html")
for asset in "${ASSETS[@]}"; do
    if [ -f "$SRC_DIR/$asset" ]; then
        cp "$SRC_DIR/$asset" "$DIST_DIR/$asset"
        echo "$(date '+%Y-%m-%d %H:%M:%S') Copied $asset"
    fi
done

# 3. Files to Compile
FILES=(
    "version.py"

#    "protocols/mpautobahn/__init__.py"
#    "protocols/mpautobahn/client.py"
#    "protocols/mpautobahn/constants.py"

    "adapters/wamp_bridge.py"
    "adapters/config_manager.py"
    "adapters/wifi.py"
    "adapters/device.py"
    "adapters/datetime.py"
    "adapters/http_api.py"

    "app/supervisor.py"
    "app/provision.py"

    "domain/state.py"
    "domain/stats.py"
    "domain/dosing.py"
    "domain/scheduler.py"
    "domain/controllers.py"
    "domain/device_service.py"
    
    "drivers/pca9685.py"
    "drivers/pwm_out.py"
    "drivers/flowsensor.py"


    "lib/file_store.py"
    "lib/mp_wamp_client.py"
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
        $MPY_CROSS -O3 -s "$rel_file" -o "$out_path" -- "$src_path"
        
        if [ $? -ne 0 ]; then
            echo "$(date '+%Y-%m-%d %H:%M:%S')  [FAIL]"
            exit 1
        fi
    else
        echo "$(date '+%Y-%m-%d %H:%M:%S') Skipping missing: $src_path"
    fi
done

echo "$(date '+%Y-%m-%d %H:%M:%S') Build Complete. Directory: $DIST_DIR"
