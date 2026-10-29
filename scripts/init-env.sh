#!/usr/bin/env bash
# Create .env from .env.example with random secrets. Never overwrites an existing .env.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -e .env ]]; then
  echo ".env already exists; not touching it" >&2
  exit 1
fi
rand() { python3 -c 'import secrets; print(secrets.token_urlsafe(32))'; }
pg=$(python3 -c 'import secrets; print(secrets.token_hex(16))')
api=$(rand); runner=$(rand); agent=$(rand)
sed -e "s#^POSTGRES_PASSWORD=.*#POSTGRES_PASSWORD=${pg}#" \
    -e "s#ohmypm:change-me@#ohmypm:${pg}@#" \
    -e "s#^OHMYPM_API_TOKEN=.*#OHMYPM_API_TOKEN=${api}#" \
    -e "s#^OHMYPM_RUNNER_TOKEN=.*#OHMYPM_RUNNER_TOKEN=${runner}#" \
    -e "s#^OHMYPM_AGENT_TOKEN=.*#OHMYPM_AGENT_TOKEN=${agent}#" \
    .env.example > .env
chmod 600 .env
echo "wrote .env (mode 600). Admin token for the Web UI / CLI: ${api}"
