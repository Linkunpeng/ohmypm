import QtQuick
import "../services"

// One project's records per day as thin columns; the empty days keep a faint tick so the
// time range stays readable.
Item {
    id: root
    property var items: []
    property int days: 14
    readonly property var buckets: Memory.daily(items, days)
    readonly property int peak: Math.max(1, ...buckets.map(b => b.total))
    readonly property real gap: 3
    implicitHeight: 26

    Repeater {
        model: root.buckets
        delegate: Rectangle {
            required property var modelData
            required property int index
            readonly property real columnWidth: (root.width - root.gap * (root.days - 1)) / root.days
            x: index * (columnWidth + root.gap)
            width: columnWidth
            height: modelData.total ? Math.max(3, modelData.total / root.peak * root.height) : 2
            y: root.height - height
            topLeftRadius: modelData.total ? Math.min(2, width / 2) : 0
            topRightRadius: topLeftRadius
            color: modelData.total ? Style.accent : Style.withAlpha(Style.text, 0.1)
        }
    }
}
