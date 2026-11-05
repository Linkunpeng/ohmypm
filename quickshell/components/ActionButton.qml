import QtQuick
import "../services"

// Glyph + label pill, like a clickable bar module.
Rectangle {
    id: root
    property string glyph
    property string text
    property color tint: Style.text
    signal clicked

    implicitWidth: row.implicitWidth + 18
    implicitHeight: 28
    radius: height / 2
    color: mouse.containsMouse ? Style.withAlpha(Style.accent, 0.3) : Style.well
    border.width: 1
    border.color: mouse.containsMouse ? Style.accent : "transparent"
    Behavior on color { ColorAnimation { duration: 120 } }

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 6
        BarText { text: root.glyph; color: root.tint }
        BarText { text: root.text; visible: text !== "" }
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }
}
