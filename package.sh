#!/usr/bin/env bash
# Упаковка yandex-direct-manager в .skill (запуск: ./package.sh)

cd "$(dirname "$0")"
python3 scripts/package_skill.py --skill-path . --output ..
