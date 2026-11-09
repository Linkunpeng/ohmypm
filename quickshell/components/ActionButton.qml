import QtQuick
import QtQuick.Controls
import "../services"

// Glyph + label pill, like a clickable bar module.
Rectangle {
    id: root
    property string glyph
    property string text
    property string tooltip
    property color tint: Style.text
    signal clicked

    implicitWidth: row.implicitWidth + 18
    implicitHeight: Math.max(28, row.implicitHeight + 10)
    opacity: enabled ? 1 : 0.4
    radius: height / 2
    color: enabled && mouse.containsMouse ? Style.withAlpha(Style.accent, 0.3) : Style.well
    border.width: 1
    border.color: mouse.containsMouse ? Style.accent : "transparent"
    Behavior on color { ColorAnimation { duration: 120 } }
    ToolTip.visible: mouse.containsMouse && tooltip !== ""
    ToolTip.text: tooltip
    ToolTip.delay: 500
    Accessible.role: Accessible.Button
    Accessible.name: tooltip || text
    Accessible.onPressAction: if (enabled) root.clicked()

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 6
        BarText { text: root.glyph; color: root.tint; visible: text !== "" }
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
