import QtQuick
import QtQuick.Layouts
import "../services"

// 概览: where the project stands, what comes next, what is open, what happened lately.
Page {
    id: page
    required property var view
    signal showTab(int index)

    readonly property var summary: view.summary
    readonly property string currentState: (summary?.current_state || summary?.overview || "").trim()
    readonly property var steps: Style.listItems(summary?.next_steps ?? "")
    // Chips: the latest milestones (done) and open issues (in progress).
    readonly property var chips: view.recent.filter(e => e.type === "milestone").slice(0, 3).map(e => ({ done: true, text: e.title }))
        .concat(view.openIssues.slice(0, 3).map(e => ({ done: false, text: e.title })))

    BarText {
        visible: page.view.detail === null
        text: "正在读取项目记忆…"
        color: Style.inactive
    }

    BarText {
        width: parent.width
        visible: text !== ""
        text: page.view.detail?.error ? "读取失败：" + page.view.detail.error : ""
        color: Style.urgent
        wrapMode: Text.Wrap
        elide: Text.ElideNone
    }

    GridLayout {
        width: parent.width
        visible: page.view.detail !== null && !page.view.detail.error
        columns: page.width >= Style.px(760) ? 2 : 1
        columnSpacing: 16
        rowSpacing: 16

        Card {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.preferredWidth: 3
            glyph: Style.glyphs.summary
            title: "项目摘要"

            Markdown {
                width: parent.width
                visible: page.currentState !== ""
                text: page.currentState
            }
            BarText {
                width: parent.width
                visible: page.currentState === ""
                text: "还没有项目摘要。Agent 在阶段结束时会用 ohmypm summary set 写入现状和下一步。"
                color: Style.inactive
                font.bold: false
                wrapMode: Text.Wrap
                elide: Text.ElideNone
            }
            Flow {
                width: parent.width
                spacing: 8
                topPadding: 4
                visible: page.chips.length > 0
                Repeater {
                    model: page.chips
                    delegate: Pill {
                        required property var modelData
                        glyph: modelData.done ? Style.glyphs.resolved : Style.glyphs.pending
                        text: Style.elide(modelData.text, 16)
                        tint: modelData.done ? Style.teal : Style.urgent
                    }
                }
                Pill {
                    glyph: Style.glyphs.more
                    tint: Style.inactive
                    interactive: true
                    onClicked: page.showTab(1)
                }
            }
        }

        Card {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.preferredWidth: 2
            glyph: Style.glyphs.rocket
            title: "下一步"

            Repeater {
                model: page.steps
                delegate: RowLayout {
                    required property var modelData
                    width: parent.width
                    spacing: 10
                    BarText {
                        Layout.alignment: Qt.AlignTop
                        text: modelData.done ? Style.glyphs.checked : Style.glyphs.unchecked
                        color: modelData.done ? Style.accent : Style.inactive
                        font.pixelSize: Style.px(15)
                    }
                    BarText {
                        Layout.fillWidth: true
                        text: modelData.text
                        color: modelData.done ? Style.inactive : Style.text
                        font.bold: false
                        font.strikeout: modelData.done
                        wrapMode: Text.Wrap
                        elide: Text.ElideNone
                    }
                }
            }
            Markdown {
                width: parent.width
                visible: page.steps.length === 0 && text !== ""
                text: (page.summary?.next_steps ?? "").trim()
            }
            BarText {
                width: parent.width
                visible: page.steps.length === 0 && (page.summary?.next_steps ?? "").trim() === ""
                text: "还没有写下一步。"
                color: Style.inactive
                font.bold: false
            }
        }
    }

    Card {
        width: parent.width
        visible: page.view.openIssueCount > 0
        glyph: Style.type("issue").glyph
        tint: Style.urgent
        title: "未解决的问题 (" + page.view.openIssueCount + ")"
        Repeater {
            model: page.view.openIssues
            delegate: EntryRow {
                required property var modelData
                required property int index
                record: modelData
                projectId: page.view.project?.id ?? ""
                showStatus: false
                divider: index < page.view.openIssues.length - 1
            }
        }
    }

    Card {
        width: parent.width
        visible: page.view.detail !== null && !page.view.detail.error
        glyph: Style.glyphs.clock
        title: "最近记录"
        trailing: BarText {
            visible: page.view.recent.length > 6
            text: "查看全部"
            color: Style.accent
            font.pixelSize: Style.px(13)
            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: page.showTab(1)
            }
        }

        BarText {
            visible: page.view.recent.length === 0
            text: "还没有记录。Agent 工作时会在这里写入里程碑、问题和决策。"
            color: Style.inactive
            font.bold: false
        }
        Repeater {
            model: page.view.recent.slice(0, 6)
            delegate: EntryRow {
                required property var modelData
                required property int index
                record: modelData
                projectId: page.view.project?.id ?? ""
                divider: index < Math.min(6, page.view.recent.length) - 1
            }
        }
    }
}
