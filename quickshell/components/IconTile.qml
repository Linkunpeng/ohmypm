import QtQuick
import "../services"

// Glyph on a rounded square, tinted with the accent when `strong`.
Rectangle {
    id: root
    property string glyph
    property int size: 40
    property bool strong: true

    width: size
    height: size
    radius: Math.round(size * 0.28)
    color: strong ? Style.withAlpha(Style.accent, 0.24) : Style.withAlpha(Style.text, 0.06)

    BarText {
        anchors.centerIn: parent
        text: root.glyph
        color: root.strong ? Style.text : Style.inactive
        font.pixelSize: Math.round(root.size * 0.45)
    }
}
