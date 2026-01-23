#!/bin/bash

# Configuration
MPY_CROSS="mpy-cross"
SRC_DIR="src"
DIST_DIR="dist"

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

    "protocols/mpautobahn/__init__.py"
    "protocols/mpautobahn/client.py"
    "protocols/mpautobahn/constants.py"

    "adapters/wamp_bridge.py"
    "adapters/config_manager.py"
    "adapters/wifi.py"
    "adapters/ntp.py"
    "adapters/http_api.py"

    "app/supervisor.py"
    "app/device_id.py"
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

    
    "lib/logging.py"
    "lib/async_websocket_client/__init__.py"
    "lib/async_websocket_client/ws.py"


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
        $MPY_CROSS "$src_path" -o "$out_path"
        
        if [ $? -ne 0 ]; then
            echo "$(date '+%Y-%m-%d %H:%M:%S')  [FAIL]"
            exit 1
        fi
    else
        echo "$(date '+%Y-%m-%d %H:%M:%S') Skipping missing: $src_path"
    fi
done

echo "$(date '+%Y-%m-%d %H:%M:%S') Build Complete. Directory: $DIST_DIR"
