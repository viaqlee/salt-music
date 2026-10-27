#!/usr/bin/env bash
# Build dist/SaltMusic-Setup-<version>.run: installer/setup.sh with the program glued on as tar.gz.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="${1:-$(grep -o '"v[0-9.]*"' "$ROOT/salt_music/ui/app.py" | head -1 | tr -d '"v')}"
OUT="$ROOT/dist/SaltMusic-Setup-$VERSION.run"

mkdir -p "$ROOT/dist"
sed "s/@VERSION@/$VERSION/g" "$ROOT/installer/setup.sh" > "$OUT"
tar -czf - -C "$ROOT" --exclude=__pycache__ --exclude='*.pyc' \
    main.py requirements.txt README.md salt_music assets >> "$OUT"
chmod +x "$OUT"
echo "$OUT ($(du -h "$OUT" | cut -f1))"
