import QtQuick
import "../services"

// Hairline between regions; `vertical` for a column divider.
Rectangle {
    property bool vertical: false
    implicitWidth: vertical ? 1 : 0
    implicitHeight: vertical ? 0 : 1
    color: Style.withAlpha(Style.text, 0.08)
}
