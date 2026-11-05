import QtQuick
import "../services"

// Rounded panel inside the window: titled block with optional content on the right.
Rectangle {
    id: root
    property string glyph
    property color tint: Style.accent
    property string title
    default property alias content: body.data
    property alias trailing: trailingSlot.data

    implicitHeight: column.implicitHeight + 36
    radius: 14
    color: Style.well
    border.width: 1
    border.color: Style.withAlpha(Style.text, 0.07)

    Column {
        id: column
        x: 18
        y: 18
        width: parent.width - 36
        spacing: 12

        Item {
            width: parent.width
            height: titleRow.implicitHeight
            visible: root.title !== ""
            Row {
                id: titleRow
                spacing: 10
                BarText { text: root.glyph; color: root.tint; font.pixelSize: 15; visible: text !== "" }
                BarText { text: root.title; font.pixelSize: 15 }
            }
            Row {
                id: trailingSlot
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                spacing: 8
            }
        }

        Column {
            id: body
            width: parent.width
            spacing: 8
        }
    }
}
