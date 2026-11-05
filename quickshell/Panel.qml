import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Hyprland
import "components"
import "services"

// An ordinary toplevel window, so Hyprland tiles it next to the others. Esc hides it.
FloatingWindow {
    id: root

    title: "ohmypm 项目面板"
    implicitWidth: 1200
    implicitHeight: 800
    minimumSize: Qt.size(640, 420)
    color: "transparent"
    visible: false

    readonly property bool focused: visible && Hyprland.activeToplevel?.activated === true && Hyprland.activeToplevel.title === title

    // Hidden: show on the current workspace. Focused: hide. Shown elsewhere: bring it here.
    function toggle(): void {
        if (focused)
            hide();
        else
            show();
    }

    function show(): void {
        // Find the project before mapping, while the user's window still has focus.
        Memory.locate(() => {
            if (visible)
                visible = false;   // remapping puts it on the current workspace
            Qt.callLater(() => {
                visible = true;
                keys.forceActiveFocus();
            });
            Memory.refresh(true);
        });
    }

    function hide(): void {
        visible = false;
    }

    function search(): void {
        if (!Memory.onDashboard)
            project.showTab(3, true);
    }

    Timer {
        interval: 30000
        repeat: true
        running: root.visible
        onTriggered: Memory.refresh(false)
    }

    // Vim-style navigation only: j / k walk the sidebar, h / l switch tabs.
    Item {
        id: keys
        focus: true
        Keys.onPressed: event => {
            switch (event.key) {
            case Qt.Key_J:
                Memory.step(1);
                break;
            case Qt.Key_K:
                Memory.step(-1);
                break;
            case Qt.Key_H:
            case Qt.Key_L:
                if (!Memory.onDashboard)
                    project.showTab((project.tab + (event.key === Qt.Key_L ? 1 : project.tabs.length - 1)) % project.tabs.length, false);
                break;
            default:
                return;
            }
            event.accepted = true;
        }
    }

    // Leaving the search field (switching project or tab) hands the keys back.
    Connections {
        target: Memory
        function onSelectedIdChanged() {
            keys.forceActiveFocus();
        }
    }

    Box {
        anchors.fill: parent
        padding: 0

        ColumnLayout {
            anchors.fill: parent
            spacing: 0

            // Title bar
            RowLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: 64
                Layout.leftMargin: 22
                Layout.rightMargin: 18
                spacing: 14

                BarText { text: Style.glyphs.brain; color: Style.accent; font.pixelSize: 26 }
                BarText { text: "ohmypm"; font.pixelSize: 20 }
                Divider { vertical: true; Layout.preferredHeight: 22 }
                BarText { text: "项目记忆 · 开发记录"; color: Style.inactive; font.bold: false; font.pixelSize: 14 }
                Item { Layout.fillWidth: true }
                BarText {
                    text: Memory.flash || (Memory.loading ? "读取中…" : Memory.refreshedAt ? Qt.formatTime(Memory.refreshedAt, "HH:mm") + " 更新" : "")
                    color: Memory.flash ? Style.teal : Style.inactive
                    font.bold: Memory.flash !== ""
                    font.pixelSize: 12
                }
                ActionButton { glyph: Style.glyphs.search; visible: !Memory.onDashboard; onClicked: root.search() }
                ActionButton { glyph: Style.glyphs.external; onClicked: Memory.openWeb() }
                ActionButton { glyph: Style.glyphs.refresh; onClicked: Memory.refresh(false) }
            }

            Divider { Layout.fillWidth: true }

            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 0

                Sidebar {
                    Layout.fillWidth: false
                    Layout.preferredWidth: Math.min(300, root.width * 0.3)
                    Layout.fillHeight: true
                    Layout.margins: 12
                    Layout.bottomMargin: 14
                }

                Divider { vertical: true; Layout.fillHeight: true }

                Item {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.leftMargin: 26
                    Layout.rightMargin: 14

                    Dashboard {
                        id: dashboard
                        anchors.fill: parent
                        visible: Memory.onDashboard && Memory.projects.length > 0
                    }

                    ProjectView {
                        id: project
                        anchors.fill: parent
                        anchors.topMargin: 20
                        visible: !Memory.onDashboard
                        onSearchDone: keys.forceActiveFocus()
                        onTabChanged: if (tab !== 3) keys.forceActiveFocus()
                    }

                    // Nothing to show yet: say what to do instead.
                    Column {
                        anchors.centerIn: parent
                        width: parent.width * 0.7
                        spacing: 10
                        visible: !dashboard.visible && !project.visible && !Memory.loading
                        BarText {
                            width: parent.width
                            horizontalAlignment: Text.AlignHCenter
                            text: Memory.error ? "读不到 ohmypm 数据" : "还没有注册项目"
                            font.pixelSize: 18
                        }
                        BarText {
                            width: parent.width
                            horizontalAlignment: Text.AlignHCenter
                            wrapMode: Text.Wrap
                            elide: Text.ElideNone
                            font.bold: false
                            color: Style.inactive
                            text: Memory.error
                                ? Memory.error + "\n确认 ohmypm 已安装（ohmypm doctor），或用 OHMYPM_BIN 指定路径。"
                                : "在项目目录运行 ohmypm register，Agent 写下的记录就会出现在这里。"
                        }
                    }
                }
            }
        }
    }
}
