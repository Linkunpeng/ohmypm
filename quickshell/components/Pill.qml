import QtQuick
import "../services"

// Small rounded label: a record type, a status or a chip.
Rectangle {
    id: root
    property string glyph
    property string text
    property color tint: Style.accent
    property bool interactive: false
    property bool selected: false
    signal clicked

    implicitWidth: row.implicitWidth + 18
    implicitHeight: Math.max(24, row.implicitHeight + 8)
    radius: height / 2
    color: Style.withAlpha(tint, selected ? 0.36 : mouse.containsMouse ? 0.26 : 0.14)
    border.width: selected ? 1 : 0
    border.color: tint

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 5
        BarText { text: root.glyph; color: root.tint; font.pixelSize: Style.px(11); visible: text !== "" }
        BarText { text: root.text; color: root.tint; font.pixelSize: Style.px(11); visible: text !== "" }
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        enabled: root.interactive
        hoverEnabled: root.interactive
        cursorShape: root.interactive ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: root.clicked()
    }
}
