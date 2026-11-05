#!/bin/sh
# Working directories of the focused window's process tree, newest process first
# (for a terminal: the shell or tool running in it). The panel matches them against
# registered project roots to pick the "current" project.
pid=$(hyprctl activewindow -j 2>/dev/null | jq -r '.pid // empty' 2>/dev/null)
[ -n "$pid" ] && [ "$pid" -gt 1 ] || exit 0

ps -e -o pid=,ppid= | awk -v root="$pid" '
    { parent[$1] = $2 }
    END {
        for (p in parent) {
            q = p
            while (q != root && q in parent && q > 1) q = parent[q]
            if (q == root) print p
        }
    }' | sort -rn | while read -r p; do
    readlink "/proc/$p/cwd" 2>/dev/null
done | awk '!seen[$0]++'
