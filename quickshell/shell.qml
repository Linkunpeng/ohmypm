//@ pragma Env QS_NO_RELOAD_POPUP=1
//@ pragma Env QT_QUICK_CONTROLS_STYLE=Basic

// ohmypm panel: a quick look at the project memory in a tiled window, styled like the
// ohmyhypr status bar.
// Run with `qs -p <ohmypm>/quickshell`; scripts/toggle.sh (SUPER + I) shows and hides it.

import QtQuick
import Quickshell
import Quickshell.Io
import "services"

ShellRoot {
    Panel {
        id: panel
    }

    // qs -p <dir> ipc call ohmypm <toggle|open|close|select|refresh|ping>
    IpcHandler {
        target: "ohmypm"

        function toggle(): void {
            panel.toggle();
        }
        function open(): void {
            panel.show();
        }
        function close(): void {
            panel.hide();
        }
        // Project name or id, e.g. `ipc call ohmypm select Robot_WS`.
        function select(project: string): void {
            const found = Memory.projects.find(p => p.id === project || p.name === project);
            if (found)
                Memory.select(found.id);
        }
        function refresh(): void {
            Memory.refresh(false);
        }
        function ping(): string {
            return "pong";
        }
    }
}
