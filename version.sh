#!/bin/bash

TODAY=$(date '+%Y-%m-%d')
VERSION_FILE="$1"
APP_VERSION_VALUE="${APP_VERSION:-}"

if [ -f "$VERSION_FILE" ]; then
    tmp_file=$(mktemp)
    if sed -E "s/^BUILD_DATE\s*=\s*\".*\"/BUILD_DATE = \"${TODAY}\"/" "$VERSION_FILE" >"$tmp_file"; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') Updated BUILD_DATE in $VERSION_FILE to ${TODAY}"
    else
        rm -f "$tmp_file"
        echo "$(date '+%Y-%m-%d %H:%M:%S') Failed updating BUILD_DATE in $VERSION_FILE" >&2
        exit 1
    fi

    if [ -n "$APP_VERSION_VALUE" ]; then
      if sed -E "s/^VERSION\s*=\s*\".*\"/VERSION = \"${APP_VERSION_VALUE}\"/" "$VERSION_FILE" >"$tmp_file"; then
          echo "$(date '+%Y-%m-%d %H:%M:%S') Updated VERSION in $VERSION_FILE to ${APP_VERSION_VALUE}"
      else
          rm -f "$tmp_file"
          echo "$(date '+%Y-%m-%d %H:%M:%S') Failed updating VERSION in $VERSION_FILE" >&2
          exit 1
      fi

      mv "$tmp_file" "$VERSION_FILE"

  fi
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') Missing $VERSION_FILE" >&2
    exit 1
fi


