#!/bin/sh
# Open the ohmypm Web UI (at a project, if given), starting `ohmypm web` in the background
# if needed.
# usage: open-web.sh [project-id]
set -eu
id=${1:-}
bin=${OHMYPM_BIN:-ohmypm}
port=${OHMYPM_WEB_PORT:-8737}
base="http://127.0.0.1:$port"
data=${OHMYPM_DATA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/ohmypm}

healthy() { curl -fsS -o /dev/null --max-time 1 "$base/api/health"; }

if ! healthy; then
    setsid "$bin" web --port "$port" >/dev/null 2>&1 < /dev/null &
    i=0
    until healthy; do
        i=$((i + 1))
        if [ "$i" -gt 50 ]; then
            notify-send -a ohmypm "ohmypm" "Web UI 没有启动，请在终端运行 ohmypm web 查看原因"
            exit 1
        fi
        sleep 0.1
    done
fi

# ?token= sets the session cookie and redirects to the clean URL.
token=$(cat "$data/web-token" 2>/dev/null || true)
exec xdg-open "$base/${id:+projects/$id}${token:+?token=$token}"
