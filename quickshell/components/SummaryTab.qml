import QtQuick
import QtQuick.Layouts
import "../services"

// 总结: the six sections of the project summary.
Page {
    id: page
    required property var view
    readonly property var summary: view.summary
    readonly property var sections: [
        { key: "overview", title: "概述", glyph: Style.glyphs.overview, tint: Style.accent },
        { key: "architecture", title: "架构", glyph: Style.glyphs.projects, tint: Style.accent },
        { key: "current_state", title: "现状", glyph: Style.glyphs.clock, tint: Style.teal },
        { key: "important_decisions", title: "重要决策", glyph: Style.type("decision").glyph, tint: Style.type("decision").color },
        { key: "known_issues", title: "已知问题", glyph: Style.type("issue").glyph, tint: Style.urgent },
        { key: "next_steps", title: "下一步", glyph: Style.glyphs.rocket, tint: Style.gold }
    ]

    BarText {
        width: parent.width
        visible: page.summary !== null && !page.summary.is_empty
        text: "第 " + (page.summary?.revision ?? 0) + " 版，" + (page.summary?.updated_by ? page.summary.updated_by + " " : "") + "更新于 " + Style.when(page.summary?.updated_at)
        color: Style.inactive
        font.bold: false
        font.pixelSize: 12
    }

    BarText {
        width: parent.width
        visible: page.summary?.is_empty === true
        text: "还没有项目摘要。Agent 在一个阶段结束时会用 ohmypm summary set 写入，各小节以 ## Overview、## Current State 等二级标题划分。"
        color: Style.inactive
        font.bold: false
        wrapMode: Text.Wrap
        elide: Text.ElideNone
    }

    GridLayout {
        width: parent.width
        visible: page.summary !== null && !page.summary.is_empty
        columns: page.width >= 760 ? 2 : 1
        columnSpacing: 16
        rowSpacing: 16

        Repeater {
            model: page.sections
            delegate: Card {
                id: card
                required property var modelData
                readonly property string body: (page.summary?.[modelData.key] ?? "").trim()
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredWidth: 1
                glyph: modelData.glyph
                tint: modelData.tint
                title: modelData.title

                Markdown {
                    width: parent.width
                    visible: card.body !== ""
                    text: card.body
                }
                BarText {
                    visible: card.body === ""
                    text: "未填写"
                    color: Style.inactive
                    font.bold: false
                }
            }
        }
    }
}
