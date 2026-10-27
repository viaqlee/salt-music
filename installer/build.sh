#!/usr/bin/env bash
# Build dist/SaltMusic-Setup-<version>.run: installer/setup.sh with the program glued on as tar.gz.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="${1:-$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT/salt_music/__init__.py")}"
OUT="$ROOT/dist/SaltMusic-Setup-$VERSION.run"

mkdir -p "$ROOT/dist"
sed "s/@VERSION@/$VERSION/g" "$ROOT/installer/setup.sh" > "$OUT"
tar -czf - -C "$ROOT" --exclude=__pycache__ --exclude='*.pyc' \
    main.py requirements.txt README.md salt_music assets >> "$OUT"
chmod +x "$OUT"
echo "$OUT ($(du -h "$OUT" | cut -f1))"
