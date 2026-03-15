import hashlib
import json
import os
import sys


def generate_ota_json(build_dir, fw_file_name=None, flash_file_name=None):
    # Calea către binarul rezultat
    bin_path = os.path.join(build_dir, "micropython.bin")
    # Calea unde va fi salvat JSON-ul (tot în folderul de build)
    json_path = os.path.join(build_dir, "firmware.json")

    if not os.path.exists(bin_path):
        print(f"Error: Not found {bin_path}")
        return

    with open(bin_path, "rb") as f:
        data = f.read()
        sha = hashlib.sha256(data).hexdigest()
        length = len(data)

    output = {
        "firmware": fw_file_name or "micropython.bin",
        "sha": sha,
        "length": length
    }

    if flash_file_name:
        output["flash"] = flash_file_name

    with open(json_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Generated: {json_path}")
    print(f"   SHA: {sha[:10]}... | Size: {length} bytes")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 gen_ota.py <directory_build> <firmware_name.bin> [flash_file.tar.gz]")
    else:
        generate_ota_json(
            sys.argv[1],
            len(sys.argv) > 2 and sys.argv[2] or None,
            len(sys.argv) > 3 and sys.argv[3] or None,
        )
