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
    readonly property Flickable main: Memory.onDashboard ? dashboard : project.pages[project.tab]

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
            project.showTab(3);
    }

    Timer {
        interval: 30000
        repeat: true
        running: root.visible
        onTriggered: Memory.refresh(false)
    }

    Item {
        id: keys
        focus: true
        Keys.onPressed: event => {
            switch (event.key) {
            case Qt.Key_Escape:
                root.hide();
                break;
            case Qt.Key_Up:
            case Qt.Key_K:
            case Qt.Key_Backtab:
                Memory.step(-1);
                break;
            case Qt.Key_Down:
            case Qt.Key_J:
            case Qt.Key_Tab:
                Memory.step(1);
                break;
            case Qt.Key_1:
            case Qt.Key_2:
            case Qt.Key_3:
            case Qt.Key_4:
                if (!Memory.onDashboard)
                    project.showTab(event.key - Qt.Key_1);
                break;
            case Qt.Key_Slash:
                root.search();
                break;
            case Qt.Key_PageDown:
            case Qt.Key_Space:
                root.main.scroll(1);
                break;
            case Qt.Key_PageUp:
                root.main.scroll(-1);
                break;
            case Qt.Key_D:
            case Qt.Key_Home:
                Memory.select("");
                break;
            case Qt.Key_T:
                Memory.openTerminal();
                break;
            case Qt.Key_W:
                Memory.openWeb();
                break;
            case Qt.Key_C:
                Memory.copyContext();
                break;
            case Qt.Key_R:
                Memory.refresh(false);
                break;
            default:
                return;
            }
            event.accepted = true;
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
