import QtQuick
import "../services"

// Footer hint: key cap followed by what it does.
Row {
    id: root
    property string keys
    property string text
    spacing: 6

    Rectangle {
        anchors.verticalCenter: parent.verticalCenter
        width: cap.implicitWidth + 12
        height: 20
        radius: 6
        color: Style.well
        border.width: 1
        border.color: Style.withAlpha(Style.text, 0.14)
        BarText {
            id: cap
            anchors.centerIn: parent
            text: root.keys
            font.pixelSize: 11
        }
    }
    BarText {
        anchors.verticalCenter: parent.verticalCenter
        text: root.text
        color: Style.inactive
        font.pixelSize: 12
    }
}
