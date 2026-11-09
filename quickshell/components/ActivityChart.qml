import QtQuick
import "../services"

// Records per day, stacked by type in Style.typeOrder. Hovering a day shows its breakdown
// in the readout line above the plot; otherwise the readout totals the whole range.
Column {
    id: root
    property var items: []
    property int days: 14
    property int plotHeight: 110

    readonly property var buckets: Memory.daily(items, days)
    readonly property int peak: Math.max(1, ...buckets.map(b => b.total))
    readonly property int total: buckets.reduce((sum, b) => sum + b.total, 0)
    property int hovered: -1
    readonly property var shown: hovered >= 0 ? buckets[hovered].counts : totals(buckets)

    spacing: 10

    function totals(list: var): var {
        const out = {};
        for (const b of list)
            for (const t in b.counts)
                out[t] = (out[t] ?? 0) + b.counts[t];
        return out;
    }

    function dayLabel(date: var): string {
        return Qt.formatDate(date, "MM-dd");
    }

    // Readout: which days, then a glyph + count per type (the legend).
    Flow {
        width: root.width
        spacing: 14
        BarText {
            text: root.hovered >= 0 ? root.dayLabel(root.buckets[root.hovered].date) + "  " + root.buckets[root.hovered].total + " 条"
                                    : "近 " + root.days + " 天  " + root.total + " 条"
        }
        Repeater {
            model: Style.typeOrder.filter(t => (root.shown[t] ?? 0) > 0)
            delegate: Row {
                required property string modelData
                readonly property var kind: Style.type(modelData)
                spacing: 5
                BarText { text: parent.kind.glyph; color: parent.kind.color }
                BarText { text: root.shown[parent.modelData] }
                BarText { text: parent.kind.label; color: Style.inactive; font.bold: false }
            }
        }
    }

    Item {
        id: plot
        // Left gutter holds the peak value.
        readonly property real gutter: Style.px(24)
        x: gutter
        width: root.width - gutter
        height: root.plotHeight
        readonly property real gap: 6
        readonly property real columnWidth: (width - gap * (root.days - 1)) / root.days
        readonly property real peakY: 8        // peak columns end here

        // Peak gridline with its value; the baseline.
        Rectangle {
            y: plot.peakY
            width: parent.width
            height: 1
            color: Style.withAlpha(Style.text, 0.08)
        }
        BarText {
            x: -plot.gutter
            width: plot.gutter - 6
            y: plot.peakY - height / 2
            horizontalAlignment: Text.AlignRight
            text: root.peak
            color: Style.inactive
            font.bold: false
            font.pixelSize: Style.px(11)
            visible: root.total > 0
        }
        Rectangle {
            y: parent.height - 1
            width: parent.width
            height: 1
            color: Style.withAlpha(Style.text, 0.18)
        }

        Repeater {
            model: root.buckets
            delegate: Item {
                id: day
                required property var modelData
                required property int index
                x: index * (plot.columnWidth + plot.gap)
                width: plot.columnWidth
                height: plot.height
                opacity: root.hovered < 0 || root.hovered === index ? 1 : 0.45

                Rectangle {
                    anchors.fill: parent
                    radius: 4
                    color: Style.wellHover
                    visible: root.hovered === day.index
                }

                // Segments bottom-up; 2px gaps between them, rounded only at the top end.
                Repeater {
                    model: {
                        const segs = [];
                        let bottom = 0;
                        const types = Style.typeOrder.concat(Object.keys(day.modelData.counts).filter(t => !Style.typeOrder.includes(t)));
                        for (const t of types) {
                            const n = day.modelData.counts[t] ?? 0;
                            if (!n)
                                continue;
                            const h = n / root.peak * (plot.height - plot.peakY);
                            segs.push({ type: t, bottom, height: h });
                            bottom += h;
                        }
                        if (segs.length)
                            segs[segs.length - 1].top = true;
                        return segs;
                    }
                    delegate: Rectangle {
                        required property var modelData
                        width: day.width
                        y: day.height - modelData.bottom - modelData.height
                        height: Math.max(2, modelData.height - (modelData.bottom > 0 ? 2 : 0))
                        color: Style.type(modelData.type).color
                        topLeftRadius: modelData.top ? Math.min(4, width / 2) : 0
                        topRightRadius: topLeftRadius
                    }
                }

                MouseArea {
                    anchors.fill: parent
                    hoverEnabled: true
                    onEntered: root.hovered = day.index
                    onExited: if (root.hovered === day.index) root.hovered = -1
                }
            }
        }

        BarText {
            anchors.centerIn: parent
            visible: root.total === 0
            text: "近 " + root.days + " 天没有新记录"
            color: Style.inactive
            font.bold: false
        }
    }

    // Day ticks: first, middle and today.
    Item {
        width: root.width
        height: Style.px(18)
        Repeater {
            model: [0, Math.floor(root.days / 2), root.days - 1]
            delegate: BarText {
                required property int modelData
                x: Math.max(0, Math.min(root.width - width, plot.x + modelData * (plot.columnWidth + plot.gap) + plot.columnWidth / 2 - width / 2))
                text: modelData === root.days - 1 ? "今天" : root.dayLabel(root.buckets[modelData].date)
                color: Style.inactive
                font.bold: false
                font.pixelSize: Style.px(11)
            }
        }
    }
}
