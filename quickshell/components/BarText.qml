import QtQuick
import "../services"

// Bar typography: bold JetBrainsMono Nerd Font in the bar's text color.
Text {
    color: Style.text
    font.family: Style.font
    font.pixelSize: Style.fontSize
    font.bold: true
    textFormat: Text.PlainText
    elide: Text.ElideRight
}
