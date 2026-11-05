import QtQuick
import "../services"

// Header statistic: glyph, value, what it counts.
Column {
    id: root
    property string glyph
    property color tint: Style.inactive
    property string value
    property string label
    spacing: 3

    BarText { text: root.glyph; color: root.tint; font.pixelSize: 16 }
    BarText { text: root.value; font.pixelSize: 20 }
    BarText { text: root.label; color: Style.inactive; font.bold: false; font.pixelSize: 11 }
}
