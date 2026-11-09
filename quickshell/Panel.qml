import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Hyprland
import "components"
import "services"

// An ordinary toplevel window, so Hyprland tiles it next to the others.
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
                Layout.preferredHeight: Math.max(64, Style.px(28) + 24)
                Layout.leftMargin: 22
                Layout.rightMargin: 18
                spacing: 8

                BarText { text: Style.glyphs.brain; color: Style.accent; font.pixelSize: Style.px(26); visible: root.width >= Style.px(700) }
                BarText { text: "ohmypm"; font.pixelSize: Style.px(20) }
                Divider { vertical: true; Layout.preferredHeight: 22; visible: subtitle.visible }
                BarText { id: subtitle; text: "项目记忆 · 开发记录"; color: Style.inactive; font.bold: false; font.pixelSize: Style.px(14); visible: root.width >= Style.px(1050) }
                Item { Layout.fillWidth: true }
                BarText {
                    Layout.fillWidth: Memory.flash !== ""
                    text: Memory.flash || (Memory.loading ? "读取中…" : Memory.refreshedAt ? Qt.formatTime(Memory.refreshedAt, "HH:mm") + " 更新" : "")
                    color: Memory.flash ? Style.teal : Style.inactive
                    font.bold: Memory.flash !== ""
                    font.pixelSize: Style.px(12)
                    visible: Memory.flash !== "" || root.width >= Style.px(950)
                }
                ActionButton { text: "A−"; tooltip: "缩小字体"; enabled: Style.fontPercent > 100; onClicked: Style.changeFontSize(-1) }
                ActionButton { text: Style.fontPercent + "%"; tooltip: "恢复默认字号"; onClicked: Style.setFontScale(1) }
                ActionButton { text: "A+"; tooltip: "放大字体"; enabled: Style.fontPercent < 200; onClicked: Style.changeFontSize(1) }
                Divider { vertical: true; Layout.preferredHeight: 22 }
                ActionButton { glyph: Style.glyphs.search; tooltip: "搜索项目记录"; visible: !Memory.onDashboard; onClicked: root.search() }
                ActionButton { glyph: Style.glyphs.external; tooltip: "打开 Web UI"; onClicked: Memory.openWeb() }
                ActionButton { glyph: Style.glyphs.refresh; tooltip: "刷新"; onClicked: Memory.refresh(false) }
            }

            Divider { Layout.fillWidth: true }

            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 0

                Sidebar {
                    Layout.fillWidth: false
                    Layout.preferredWidth: Math.min(Style.px(300), root.width * 0.3)
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
                            font.pixelSize: Style.px(18)
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
