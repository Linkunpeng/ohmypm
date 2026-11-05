import QtQuick
import "../services"

// 搜索: full-text search over this project's records and summary, as you type.
Page {
    id: page
    required property var view
    signal done                            // Esc: give the keyboard back to the panel
    signal showSummary

    property string query
    property var results: []
    property string error
    property bool searching

    function focusInput(): void {
        Qt.callLater(() => input.forceActiveFocus());
    }

    function reset(): void {
        input.text = "";
        query = "";
        results = [];
        error = "";
    }

    function run(): void {
        const q = input.text.trim();
        if (!q || !view.project) {
            query = "";
            results = [];
            return;
        }
        searching = true;
        query = q;
        Memory.search(view.project.id, q, (items, message) => {
            results = items.filter(i => i.kind !== "project");
            error = message;
            searching = false;
        });
    }

    Timer {
        id: debounce
        interval: 250
        onTriggered: page.run()
    }

    Rectangle {
        width: parent.width
        height: 46
        radius: 12
        color: Style.well
        border.width: 1
        border.color: input.activeFocus ? Style.accent : Style.withAlpha(Style.text, 0.1)

        BarText {
            id: icon
            x: 16
            anchors.verticalCenter: parent.verticalCenter
            text: Style.glyphs.search
            color: input.activeFocus ? Style.accent : Style.inactive
            font.pixelSize: 16
        }
        TextInput {
            id: input
            anchors.left: icon.right
            anchors.leftMargin: 12
            anchors.right: parent.right
            anchors.rightMargin: 16
            anchors.verticalCenter: parent.verticalCenter
            color: Style.text
            selectionColor: Style.withAlpha(Style.accent, 0.5)
            font.family: Style.font
            font.pixelSize: 14
            clip: true
            onTextChanged: debounce.restart()
            Keys.onReturnPressed: page.run()
            Keys.onEscapePressed: page.done()

            BarText {
                anchors.verticalCenter: parent.verticalCenter
                visible: input.text === ""
                text: "搜索记录和摘要，支持中文和 \"短语\""
                color: Style.inactive
                font.bold: false
                font.pixelSize: 14
            }
        }
    }

    BarText {
        width: parent.width
        text: page.searching ? "搜索中…"
            : page.error ? "搜索失败：" + page.error
            : page.query ? (page.results.length ? page.results.length + " 条结果" : "没有找到「" + page.query + "」")
            : "按 / 随时开始搜索，Esc 返回。"
        color: page.error ? Style.urgent : Style.inactive
        font.bold: false
        font.pixelSize: 12
    }

    Column {
        width: parent.width
        spacing: 2
        Repeater {
            model: page.results
            delegate: Loader {
                required property var modelData
                required property int index
                width: parent.width
                sourceComponent: modelData.kind === "summary" ? summaryHit : entryHit

                Component {
                    id: entryHit
                    EntryRow {
                        record: modelData
                        projectId: page.view.project?.id ?? ""
                        showExcerpt: true
                        divider: index < page.results.length - 1
                    }
                }
                Component {
                    id: summaryHit
                    Rectangle {
                        width: parent?.width ?? 0
                        implicitHeight: hit.implicitHeight + 22
                        radius: 10
                        color: hitMouse.containsMouse ? Style.wellHover : "transparent"
                        Column {
                            id: hit
                            x: 12
                            y: 11
                            width: parent.width - 24
                            spacing: 6
                            Row {
                                spacing: 10
                                BarText { text: Style.glyphs.summary; color: Style.accent; font.pixelSize: 15 }
                                BarText { text: "项目摘要" }
                            }
                            BarText {
                                x: 30
                                width: parent.width - 30
                                text: Style.plain(modelData.snippet ?? "")
                                color: Style.inactive
                                font.bold: false
                                font.pixelSize: 12
                            }
                        }
                        MouseArea {
                            id: hitMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: page.showSummary()
                        }
                    }
                }
            }
        }
    }
}
