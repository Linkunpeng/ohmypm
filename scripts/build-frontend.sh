#!/usr/bin/env bash
# Build the Web UI into src/ohmypm/webui/dist (served by `ohmypm web`).
set -euo pipefail
cd "$(dirname "$0")/../frontend"
pnpm install --frozen-lockfile
pnpm build
echo "Web UI built into src/ohmypm/webui/dist"
