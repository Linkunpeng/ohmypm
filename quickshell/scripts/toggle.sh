#!/bin/sh
# Show / hide the ohmypm panel (bound to SUPER + I). Starts the Quickshell instance on
# first use; `toggle.sh start` only starts it (for autostart).
dir=$(dirname "$(dirname "$(readlink -f "$0")")")
action=${1:-toggle}

# Hyprland's exec environment may lack the uv tool directory.
case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *) PATH="$HOME/.local/bin:$PATH"; export PATH ;;
esac

call() { qs -p "$dir" ipc call ohmypm "$1" >/dev/null 2>&1; }

if [ "$action" = start ]; then
    call ping || qs -n -d -p "$dir" >/dev/null 2>&1
    exit 0
fi

call "$action" && exit 0
qs -n -d -p "$dir" >/dev/null 2>&1
i=0
while [ "$i" -lt 50 ]; do
    sleep 0.1
    call "$action" && exit 0
    i=$((i + 1))
done
notify-send -a ohmypm "ohmypm" "面板没有启动：qs -p $dir 查看错误"
exit 1
