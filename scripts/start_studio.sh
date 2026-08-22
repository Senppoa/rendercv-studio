#!/usr/bin/env bash
# 在浏览器中启动 YAML Studio。
set -e
cd "$(dirname "$0")/.."
python3 tools/yaml_studio.py --root examples "$@"
