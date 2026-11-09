import QtQuick
import QtQuick.Layouts
import "../services"

// 总览: every project at a glance — totals, the last two weeks, what is still open,
// what changed, and one tile per project.
Page {
    id: root
    readonly property var recentWeek: Memory.activity.filter(e => Style.daysAgo(e.created_at) < 7)
    readonly property int activeProjects: new Set(recentWeek.map(e => e.project_id)).size
    readonly property int totalRecords: Memory.projects.reduce((sum, p) => sum + p.entry_count, 0)

    function activityOf(id: string): var {
        return Memory.activity.filter(e => e.project_id === id);
    }

    GridLayout {
        width: parent.width
        columns: root.width >= Style.px(700) ? 2 : 1
        columnSpacing: 16
        rowSpacing: 16

        RowLayout {
            Layout.fillWidth: true
            spacing: 16
            IconTile {
                glyph: Style.glyphs.dashboard
                size: 60
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 4
                BarText {
                    text: "总览"
                    font.pixelSize: Style.px(24)
                }
                BarText {
                    Layout.fillWidth: true
                    text: Memory.projects.length + " 个项目，" + root.activeProjects + " 个近 7 天有新记录"
                    color: Style.inactive
                    font.bold: false
                }
            }
        }
        Flow {
            Layout.fillWidth: true
            spacing: 24
            StatColumn {
                glyph: Style.glyphs.summary
                value: root.totalRecords
                label: "记录"
            }
            StatColumn {
                glyph: Style.type("issue").glyph
                tint: Style.urgent
                value: Memory.openIssueItems.length
                label: "未解决"
            }
            StatColumn {
                glyph: Style.glyphs.pulse
                tint: Style.teal
                value: root.recentWeek.length
                label: "近 7 天新增"
            }
        }
    }

    Card {
        width: parent.width
        glyph: Style.glyphs.chart
        title: "记录活动"
        ActivityChart {
            width: parent.width
            items: Memory.activity
        }
    }

    GridLayout {
        width: parent.width
        columns: root.width >= Style.px(860) ? 2 : 1
        columnSpacing: 16
        rowSpacing: 16

        Card {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.preferredWidth: 1
            glyph: Style.type("issue").glyph
            tint: Style.urgent
            title: "未解决的问题"

            BarText {
                visible: Memory.openIssueItems.length === 0
                text: "没有未解决的问题。"
                color: Style.inactive
                font.bold: false
            }
            Repeater {
                model: Memory.openIssueItems.slice(0, 6)
                delegate: EntryRow {
                    required property var modelData
                    required property int index
                    record: modelData
                    projectId: modelData.project_id
                    projectName: Memory.projectName(modelData.project_id)
                    showType: false
                    showStatus: false
                    divider: index < Math.min(6, Memory.openIssueItems.length) - 1
                }
            }
            BarText {
                visible: Memory.openIssueItems.length > 6
                text: "另有 " + (Memory.openIssueItems.length - 6) + " 个，在各项目中查看"
                color: Style.inactive
                font.bold: false
                font.pixelSize: Style.px(12)
            }
        }

        Card {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.preferredWidth: 1
            glyph: Style.glyphs.clock
            title: "最新动态"

            BarText {
                visible: Memory.activity.length === 0
                text: "近 14 天没有新记录。"
                color: Style.inactive
                font.bold: false
            }
            Repeater {
                model: Memory.activity.slice(0, 6)
                delegate: EntryRow {
                    required property var modelData
                    required property int index
                    record: modelData
                    projectId: modelData.project_id
                    projectName: Memory.projectName(modelData.project_id)
                    showType: false
                    divider: index < Math.min(6, Memory.activity.length) - 1
                }
            }
        }
    }

    Card {
        id: projects
        width: parent.width
        glyph: Style.glyphs.projects
        title: "项目 (" + Memory.projects.length + ")"

        GridLayout {
            width: parent.width
            columns: Math.max(1, Math.floor((width + 10) / (Style.px(280) + 10)))
            columnSpacing: 10
            rowSpacing: 10
            Repeater {
                model: Memory.projects
                delegate: ProjectTile {
                    required property var modelData
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    project: modelData
                    activity: root.activityOf(modelData.id)
                }
            }
        }
    }
}
