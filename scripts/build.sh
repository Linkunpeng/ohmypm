#!/usr/bin/env bash
# Build the frontend and a wheel + sdist that include the compiled Web UI.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
"$root/scripts/build-frontend.sh"
cd "$root"
uv build
ls -l dist/
