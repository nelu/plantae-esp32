#!/bin/bash

# Configuration
MPY_CROSS="mpy-cross"
SRC_DIR="src"
DIST_DIR="dist"

echo "Building Production Image in $DIST_DIR..."

# 1. Clean/Create Dist
rm -rf "$DIST_DIR"
mkdir -p "$DIST_DIR"

# 2. Copy Assets (main.py, etc)
ASSETS=("main.py" "boot.py" "config.json" "version.py")
for asset in "${ASSETS[@]}"; do
    if [ -f "$SRC_DIR/$asset" ]; then
        cp "$SRC_DIR/$asset" "$DIST_DIR/$asset"
        echo "Copied $asset"
    fi
done

# 3. Files to Compile
FILES=(
    "protocols/mpautobahn/__init__.py"
    "protocols/mpautobahn/client.py"
    "protocols/mpautobahn/constants.py"
    "protocols/mpautobahn/url.py"
    "protocols/mpautobahn/websocket.py"
    
    "adapters/wamp_bridge.py"
    "adapters/config_manager.py"
    "adapters/wifi.py"
    "adapters/ntp.py"
    "adapters/http_api.py"
    
    "app/supervisor.py"
    "app/device_id.py"
    
    "domain/state.py"
    "domain/dosing.py"
    "domain/scheduler.py"
    "domain/controllers.py"
    
    "drivers/pca9685.py"
    "drivers/pwm_out.py"
    "drivers/flowsensor/__init__.py"
    "drivers/flowsensor/flowsensor.py"
    "drivers/flowsensor/types.py"
    
    "lib/logging.py"
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
        
        echo "Compiling $rel_file -> $out_path"
        $MPY_CROSS "$src_path" -o "$out_path"
        
        if [ $? -ne 0 ]; then
            echo "  [FAIL]"
            exit 1
        fi
    else
        echo "Skipping missing: $src_path"
    fi
done

echo "Build Complete. Directory: $DIST_DIR"
