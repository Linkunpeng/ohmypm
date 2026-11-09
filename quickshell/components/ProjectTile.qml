import QtQuick
import "../services"

// A project on the dashboard: counts and its last two weeks. Click to open it.
Rectangle {
    id: root
    required property var project
    property var activity: []
    readonly property int issues: Memory.openIssues[project.id] ?? 0

    implicitHeight: column.implicitHeight + 28
    radius: 12
    color: mouse.containsMouse ? Style.wellHover : Style.well
    border.width: 1
    border.color: mouse.containsMouse ? Style.accent : "transparent"
    Behavior on color { ColorAnimation { duration: 120 } }

    Column {
        id: column
        x: 14
        y: 14
        width: parent.width - 28
        spacing: 6

        BarText {
            width: parent.width
            text: root.project.name
            color: root.project.root_exists ? Style.text : Style.inactive
        }
        BarText {
            width: parent.width
            text: Style.home(root.project.root_path)
            color: Style.inactive
            font.bold: false
            font.pixelSize: Style.px(11)
        }
        Flow {
            width: parent.width
            spacing: 10
            BarText {
                text: root.project.entry_count + " 条记录"
                font.bold: false
                font.pixelSize: Style.px(12)
            }
            BarText {
                visible: root.issues > 0
                text: Style.type("issue").glyph + " " + root.issues
                color: Style.urgent
                font.pixelSize: Style.px(12)
            }
            BarText {
                text: Style.ago(root.project.last_activity_at)
                color: Style.inactive
                font.bold: false
                font.pixelSize: Style.px(12)
            }
        }
        Sparkline {
            width: parent.width
            items: root.activity
        }
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: Memory.select(root.project.id)
    }
}
