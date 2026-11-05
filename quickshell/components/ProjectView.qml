import QtQuick
import QtQuick.Layouts
import "../services"

// The selected project: name and key numbers, then 概览 / 时间线 / 总结 / 搜索.
ColumnLayout {
    id: root
    readonly property var project: Memory.selected
    readonly property var detail: Memory.detail
    readonly property var context: detail?.context ?? null
    readonly property var summary: context?.summary ?? null
    readonly property var recent: detail?.recent ?? []
    readonly property var openIssues: (context?.sections ?? []).find(s => s.key === "open_issues")?.entries ?? []
    readonly property int openIssueCount: context?.stats?.open_issues ?? openIssues.length
    // Days with at least one record (among the loaded records).
    readonly property int activeDays: new Set(recent.map(e => Style.startOfDay(e.created_at).getTime())).size

    readonly property var tabs: [
        { title: "概览", glyph: Style.glyphs.overview },
        { title: "时间线", glyph: Style.glyphs.timeline },
        { title: "总结", glyph: Style.glyphs.summary },
        { title: "搜索", glyph: Style.glyphs.search }
    ]
    property int tab: 0
    readonly property var pages: [overview, timeline, summaryPage, search]
    signal searchDone                      // Esc in the search field

    spacing: 0

    // focusSearch: put the cursor in the search field (clicks), not when moving with h / l.
    function showTab(index: int, focusSearch: bool): void {
        tab = index;
        if (index === 3 && focusSearch)
            search.focusInput();
    }

    onProjectChanged: {
        for (const page of pages)
            page.contentY = 0;
        timeline.filter = "";
        search.reset();
    }

    RowLayout {
        Layout.fillWidth: true
        Layout.topMargin: 4
        spacing: 16

        IconTile {
            glyph: Style.glyphs.folder
            size: 60
        }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 4
            BarText {
                Layout.fillWidth: true
                text: root.project?.name ?? ""
                font.pixelSize: 24
            }
            BarText {
                Layout.fillWidth: true
                text: Style.home(root.project?.root_path ?? "")
                color: Style.inactive
                font.bold: false
            }
        }
        RowLayout {
            spacing: 32
            StatColumn {
                glyph: Style.glyphs.summary
                value: root.project?.entry_count ?? 0
                label: "记录"
            }
            StatColumn {
                glyph: Style.glyphs.calendar
                value: root.activeDays + " 天"
                label: "活跃"
            }
            StatColumn {
                glyph: Style.glyphs.clock
                value: Style.day(root.project?.last_activity_at)
                label: "最近更新"
            }
        }
    }

    BarText {
        Layout.fillWidth: true
        Layout.topMargin: 14
        visible: text !== ""
        text: root.project?.description ?? ""
        font.bold: false
        wrapMode: Text.Wrap
        elide: Text.ElideNone
    }

    // Tabs, with the project actions on the right.
    Item {
        Layout.fillWidth: true
        Layout.topMargin: 16
        Layout.preferredHeight: 46

        Row {
            height: parent.height
            spacing: 4
            Repeater {
                model: root.tabs
                delegate: Item {
                    id: tabItem
                    required property var modelData
                    required property int index
                    readonly property bool chosen: index === root.tab
                    width: tabLabel.implicitWidth + 30
                    height: parent.height

                    Row {
                        id: tabLabel
                        anchors.centerIn: parent
                        spacing: 8
                        BarText {
                            text: tabItem.modelData.glyph
                            color: tabItem.chosen ? Style.accent : Style.inactive
                            font.pixelSize: 15
                        }
                        BarText {
                            text: tabItem.modelData.title
                            color: tabItem.chosen || tabMouse.containsMouse ? Style.text : Style.inactive
                            font.pixelSize: 14
                        }
                    }
                    Rectangle {
                        anchors.bottom: parent.bottom
                        width: parent.width
                        height: 2
                        radius: 1
                        color: Style.accent
                        visible: tabItem.chosen
                    }
                    MouseArea {
                        id: tabMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.showTab(tabItem.index, true)
                    }
                }
            }
        }

        Row {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: 8
            ActionButton { glyph: Style.glyphs.terminal; text: "终端"; onClicked: Memory.openTerminal() }
            ActionButton { glyph: Style.glyphs.copy; text: "复制上下文"; onClicked: Memory.copyContext() }
        }

        Divider {
            anchors.bottom: parent.bottom
            width: parent.width
        }
    }

    StackLayout {
        Layout.fillWidth: true
        Layout.fillHeight: true
        currentIndex: root.tab

        OverviewTab {
            id: overview
            view: root
            onShowTab: index => root.showTab(index, false)
        }
        TimelineTab {
            id: timeline
            view: root
        }
        SummaryTab {
            id: summaryPage
            view: root
        }
        SearchTab {
            id: search
            view: root
            onDone: root.searchDone()
            onShowSummary: root.showTab(2, false)
        }
    }
}
