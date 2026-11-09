import QtQuick
import QtQuick.Layouts
import "../services"

// One record: type glyph, title, status and type pills, time. Click to read the full text.
// `record` may be a log list item, a context entry or a search hit.
Item {
    id: root
    required property var record
    required property string projectId
    property string projectName          // shown in lists that mix projects
    property bool showExcerpt: false
    property bool showType: true         // off where the glyph alone is enough
    property bool showStatus: true       // off in lists that only hold open issues
    property bool divider: true
    property bool expanded: false

    readonly property string type: record.type ?? record.entry_type ?? "note"
    readonly property var kind: Style.type(type)
    readonly property var full: Memory.entry(projectId, record.sequence)
    readonly property string body: full?.content ?? record.content ?? record.excerpt ?? record.snippet ?? ""
    readonly property string excerpt: Style.plain(record.excerpt ?? record.snippet ?? record.content ?? "")
    readonly property bool hypothesis: (record.metadata?.confidence ?? "") === "hypothesis" || record.unverified === true
    readonly property var status: ({
            open: { text: "未解决", color: Style.urgent },
            resolved: { text: "已解决", color: Style.teal },
            obsolete: { text: "已过时", color: Style.inactive }
        })[record.status] ?? null

    width: parent?.width ?? 0
    implicitHeight: column.implicitHeight + 22

    Rectangle {
        anchors.fill: parent
        anchors.bottomMargin: 1
        radius: 10
        color: root.expanded || mouse.containsMouse ? Style.wellHover : "transparent"
        Behavior on color { ColorAnimation { duration: 120 } }
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: {
            root.expanded = !root.expanded;
            if (root.expanded)
                Memory.loadEntry(root.projectId, root.record.sequence);
        }
    }

    Column {
        id: column
        x: 12
        y: 11
        width: root.width - 24
        spacing: 6

        RowLayout {
            width: parent.width
            spacing: 10
            BarText {
                Layout.preferredWidth: Style.px(20)
                text: root.kind.glyph
                color: root.kind.color
                font.pixelSize: Style.px(15)
            }
            BarText {
                Layout.fillWidth: true
                text: root.record.title
                wrapMode: Text.Wrap
                elide: Text.ElideNone
            }
        }

        Flow {
            x: Style.px(20) + 10
            width: parent.width - x
            spacing: 6
            BarText {
                visible: root.projectName !== ""
                width: Math.min(implicitWidth, parent.width)
                text: root.projectName
                color: Style.accent
                font.pixelSize: Style.px(12)
            }
            Pill { visible: root.hypothesis; text: "待验证"; tint: Style.gold }
            Pill { visible: root.showStatus && root.status !== null; text: root.status?.text ?? ""; tint: root.status?.color ?? Style.inactive }
            Pill { visible: root.showType; text: root.kind.label; tint: root.kind.color }
            BarText {
                text: Style.when(root.record.created_at)
                color: Style.inactive
                font.bold: false
                font.pixelSize: Style.px(12)
            }
        }

        BarText {
            x: Style.px(20) + 10
            width: parent.width - x
            visible: root.showExcerpt && !root.expanded && text !== ""
            text: root.excerpt
            color: Style.inactive
            font.bold: false
            font.pixelSize: Style.px(12)
        }

        Markdown {
            x: Style.px(20) + 10
            width: parent.width - x
            visible: root.expanded
            text: root.body || "_（没有正文）_"
            topPadding: 4
            bottomPadding: 4
        }
    }

    Divider {
        visible: root.divider
        anchors.bottom: parent.bottom
        x: 12
        width: parent.width - 24
    }
}
