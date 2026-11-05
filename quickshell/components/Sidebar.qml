import QtQuick
import QtQuick.Layouts
import "../services"

// Left column: the dashboard, then every registered project (most recently active first).
ColumnLayout {
    id: root
    spacing: 0

    component Entry: Rectangle {
        id: entry
        property string glyph
        property string title
        property string subtitle
        property string time
        property int issues
        property bool recent                 // a record today
        property bool dim
        property bool chosen
        signal clicked

        width: ListView.view ? ListView.view.width : parent.width
        height: 64
        radius: 12
        color: chosen ? Style.withAlpha(Style.accent, 0.32) : mouse.containsMouse ? Style.wellHover : "transparent"
        Behavior on color { ColorAnimation { duration: 120 } }

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 10
            anchors.rightMargin: 12
            spacing: 12

            IconTile {
                glyph: entry.glyph
                size: 40
                strong: entry.chosen
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 3
                Item {
                    Layout.fillWidth: true
                    implicitHeight: name.implicitHeight
                    BarText {
                        id: name
                        width: Math.min(implicitWidth, parent.width - 14)
                        text: entry.title
                        color: entry.dim ? Style.inactive : Style.text
                        font.pixelSize: 14
                    }
                    Rectangle {
                        visible: entry.recent
                        x: name.width + 7
                        anchors.verticalCenter: name.verticalCenter
                        width: 7
                        height: 7
                        radius: 4
                        color: Style.neon
                    }
                }
                BarText {
                    Layout.fillWidth: true
                    text: entry.subtitle
                    color: Style.inactive
                    font.bold: false
                    font.pixelSize: 11
                }
            }
            ColumnLayout {
                spacing: 3
                BarText {
                    Layout.alignment: Qt.AlignRight
                    text: entry.time
                    color: Style.inactive
                    font.bold: false
                    font.pixelSize: 11
                }
                BarText {
                    Layout.alignment: Qt.AlignRight
                    visible: entry.issues > 0
                    text: Style.type("issue").glyph + " " + entry.issues
                    color: Style.urgent
                    font.pixelSize: 11
                }
            }
        }

        MouseArea {
            id: mouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: entry.clicked()
        }
    }

    ListView {
        id: list
        Layout.fillWidth: true
        Layout.fillHeight: true
        model: Memory.projects
        currentIndex: Memory.projects.findIndex(p => p.id === Memory.selectedId)
        spacing: 4
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        highlightMoveDuration: 0

        header: Column {
            width: ListView.view.width
            spacing: 4
            bottomPadding: 4

            Entry {
                glyph: Style.glyphs.dashboard
                title: "总览"
                subtitle: "所有项目的问题与动态"
                issues: Memory.openIssueItems.length
                chosen: Memory.onDashboard
                onClicked: Memory.select("")
            }

            BarText {
                x: 10
                topPadding: 14
                bottomPadding: 6
                text: "项目 (" + Memory.projects.length + ")"
                color: Style.inactive
                font.pixelSize: 13
            }
        }

        delegate: Entry {
            required property var modelData
            glyph: Style.glyphs.folder
            title: modelData.name
            subtitle: Style.home(modelData.root_path)
            time: modelData.root_exists ? Style.ago(modelData.last_activity_at) : "目录不存在"
            issues: Memory.openIssues[modelData.id] ?? 0
            recent: modelData.last_activity_at ? Style.daysAgo(modelData.last_activity_at) === 0 : false
            dim: !modelData.root_exists
            chosen: modelData.id === Memory.selectedId
            onClicked: Memory.select(modelData.id)
        }
    }
}
