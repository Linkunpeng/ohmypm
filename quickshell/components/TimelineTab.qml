import QtQuick
import "../services"

// 时间线: every loaded record by day, filterable by type.
Page {
    id: page
    required property var view
    property string filter: ""             // record type; "" shows all

    readonly property var counts: {
        const out = {};
        for (const e of view.recent)
            out[e.type] = (out[e.type] ?? 0) + 1;
        return out;
    }
    readonly property var types: Style.typeOrder.filter(t => counts[t]).concat(Object.keys(counts).filter(t => !Style.typeOrder.includes(t)))
    readonly property var days: {
        const out = [];
        const newestFirst = view.recent.slice().sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
        for (const e of newestFirst) {
            if (filter && e.type !== filter)
                continue;
            const key = Style.startOfDay(e.created_at).getTime();
            if (!out.length || out[out.length - 1].key !== key)
                out.push({ key, iso: e.created_at, items: [] });
            out[out.length - 1].items.push(e);
        }
        return out;
    }

    TypeSpectrum {
        width: parent.width
        counts: page.counts
        showLegend: false
    }

    Flow {
        width: parent.width
        spacing: 8
        visible: page.view.recent.length > 0
        Pill {
            text: "全部 " + page.view.recent.length
            tint: Style.accent
            selected: page.filter === ""
            interactive: true
            onClicked: page.filter = ""
        }
        Repeater {
            model: page.types
            delegate: Pill {
                required property string modelData
                glyph: Style.type(modelData).glyph
                text: Style.type(modelData).label + " " + page.counts[modelData]
                tint: Style.type(modelData).color
                selected: page.filter === modelData
                interactive: true
                onClicked: page.filter = page.filter === modelData ? "" : modelData
            }
        }
    }

    BarText {
        visible: page.view.recent.length === 0 && page.view.detail !== null
        text: "还没有记录。"
        color: Style.inactive
        font.bold: false
    }

    Repeater {
        model: page.days
        delegate: Column {
            id: day
            required property var modelData
            width: parent.width
            spacing: 2

            Row {
                spacing: 8
                bottomPadding: 4
                BarText { text: Style.glyphs.calendar; color: Style.inactive }
                BarText {
                    readonly property int ago: Style.daysAgo(day.modelData.iso)
                    text: Style.day(day.modelData.iso) + (ago < 7 ? "  " + Qt.formatDate(new Date(day.modelData.iso), "MM-dd") : "")
                    color: Style.inactive
                }
                BarText {
                    text: day.modelData.items.length + " 条"
                    color: Style.inactive
                    font.bold: false
                }
            }
            Repeater {
                model: day.modelData.items
                delegate: EntryRow {
                    required property var modelData
                    required property int index
                    record: modelData
                    projectId: page.view.project?.id ?? ""
                    showExcerpt: true
                    divider: index < day.modelData.items.length - 1
                }
            }
        }
    }

    BarText {
        width: parent.width
        visible: page.view.project !== null && page.view.recent.length < page.view.project.entry_count
        text: "这里显示最近 " + page.view.recent.length + " 条，完整时间线在 Web UI 中查看。"
        color: Style.inactive
        font.bold: false
        font.pixelSize: Style.px(12)
    }
}
