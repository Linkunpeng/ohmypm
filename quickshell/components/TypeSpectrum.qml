import QtQuick
import "../services"

// What the project's memory is made of: one proportional segment per record type,
// then the counts.
Column {
    id: root
    property var counts: ({})
    property bool showLegend: true
    readonly property var present: Style.typeOrder.filter(t => (counts[t] ?? 0) > 0)
        .concat(Object.keys(counts).filter(t => !Style.typeOrder.includes(t) && counts[t] > 0))
    readonly property int total: present.reduce((sum, t) => sum + counts[t], 0)
    visible: total > 0
    spacing: 10

    Row {
        id: strip
        width: root.width
        height: 6
        spacing: 3
        Repeater {
            model: root.present
            delegate: Rectangle {
                required property string modelData
                width: (strip.width - strip.spacing * (root.present.length - 1)) * root.counts[modelData] / root.total
                height: strip.height
                radius: 3
                color: Style.type(modelData).color
            }
        }
    }

    Flow {
        width: root.width
        visible: root.showLegend
        spacing: 14
        Repeater {
            model: root.present
            delegate: Row {
                required property string modelData
                readonly property var t: Style.type(modelData)
                spacing: 5
                BarText { text: parent.t.glyph; color: parent.t.color }
                BarText { text: root.counts[parent.modelData] }
                BarText { text: parent.t.label; color: Style.inactive; font.bold: false }
            }
        }
    }
}
