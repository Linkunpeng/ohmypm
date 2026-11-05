pragma Singleton

// Look of the panel: the ohmyhypr status bar's box style (ohmyhypr/shell/services/BarStyle.qml)
// on top of the live ohmyhypr theme ($XDG_STATE_HOME/ohmyhypr/theme.json, written by
// `omh theme apply`). Without ohmyhypr the builtin palette below is used.

import QtQuick
import Quickshell
import Quickshell.Io

Singleton {
    id: root

    readonly property string themePath: (Quickshell.env("XDG_STATE_HOME") || Quickshell.env("HOME") + "/.local/state") + "/ohmyhypr/theme.json"
    property var theme: ({})
    readonly property var palette: theme.palette ?? ({})

    property color accent: palette.accent ?? "#8aadf4"
    property color accentAlt: palette.accent_alt ?? "#c6a0f6"
    property color urgent: palette.urgent ?? "#ed8796"
    Behavior on accent { ColorAnimation { duration: 450 } }
    Behavior on accentAlt { ColorAnimation { duration: 450 } }
    Behavior on urgent { ColorAnimation { duration: 450 } }

    // Bar metrics and colors (waybar "[Dark] Latte-Wallust combined").
    readonly property string font: "JetBrainsMono Nerd Font"
    readonly property int fontSize: 13
    readonly property int radius: 15
    readonly property int padding: 6
    readonly property color box: Qt.rgba(1 / 255, 1 / 255, 1 / 255, 0.82)   // bar boxes are 0.5; paragraphs need more
    readonly property color well: Qt.rgba(1, 1, 1, 0.045)
    readonly property color wellHover: Qt.rgba(1, 1, 1, 0.09)
    readonly property color border: accent
    readonly property color text: "#e5d9f5"
    readonly property color inactive: "#6e6a86"
    readonly property color gold: "#ffd700"
    readonly property color sapphire: "#209fb5"
    readonly property color mauve: "#8839ef"
    readonly property color sky: "#04a5e5"
    readonly property color teal: "#179299"
    readonly property color neon: "#39ff14"
    readonly property color tooltip: "#1e1e2e"

    // Record types (ohmypm's default config): a Nerd Font glyph and a color from the bar's
    // hue families, stepped for the dark surface. typeOrder is the stacking order; it was
    // checked with a palette validator (adjacent pairs pass; the glyph legend and the gaps
    // between segments carry identity for color-blind readers).
    readonly property var types: ({
            milestone: { glyph: String.fromCodePoint(0xF023B), color: "#c98500", label: "里程碑" },
            decision: { glyph: String.fromCodePoint(0xF062C), color: "#9085e9", label: "决策" },
            issue: { glyph: String.fromCodePoint(0xF00E4), color: "#e66767", label: "问题" },
            knowledge: { glyph: String.fromCodePoint(0xF0335), color: "#199e70", label: "知识" },
            note: { glyph: String.fromCodePoint(0xF03EB), color: "#d95926", label: "笔记" },
            artifact: { glyph: String.fromCodePoint(0xF03D6), color: "#3987e5", label: "产物" }
        })
    readonly property var typeOrder: ["milestone", "decision", "issue", "knowledge", "note", "artifact"]

    function type(name: string): var {
        return types[name] ?? { glyph: String.fromCodePoint(0xF03EB), color: inactive, label: name };
    }

    readonly property var glyphs: ({
            brain: String.fromCodePoint(0xF09D1),
            dashboard: String.fromCodePoint(0xF056E),
            chart: String.fromCodePoint(0xF0128),
            pulse: String.fromCodePoint(0xF0430),
            projects: String.fromCodePoint(0xF0253),
            folder: String.fromCodePoint(0xF024B),
            search: String.fromCodePoint(0xF0349),
            external: String.fromCodePoint(0xF03CC),
            overview: String.fromCodePoint(0xF06A1),
            timeline: String.fromCodePoint(0xF0718),
            summary: String.fromCodePoint(0xF09EE),
            rocket: String.fromCodePoint(0xF14DE),
            calendar: String.fromCodePoint(0xF00ED),
            pending: String.fromCodePoint(0xF0766),
            unchecked: String.fromCodePoint(0xF0131),
            checked: String.fromCodePoint(0xF0135),
            more: String.fromCodePoint(0xF01D8),
            terminal: String.fromCodePoint(0xF018D),
            copy: String.fromCodePoint(0xF018F),
            web: String.fromCodePoint(0xF059F),
            refresh: String.fromCodePoint(0xF0450),
            close: String.fromCodePoint(0xF0156),
            resolved: String.fromCodePoint(0xF05E0),
            clock: String.fromCodePoint(0xF0954)
        })

    function withAlpha(c: color, a: real): color {
        return Qt.rgba(c.r, c.g, c.b, a);
    }

    // "3 分钟前" for recent timestamps, a date for older ones.
    function ago(iso: var): string {
        if (!iso)
            return "暂无活动";
        const then = new Date(iso);
        const s = Math.max(0, (Date.now() - then.getTime()) / 1000);
        if (s < 60)
            return "刚刚";
        if (s < 3600)
            return Math.floor(s / 60) + " 分钟前";
        if (s < 86400)
            return Math.floor(s / 3600) + " 小时前";
        if (s < 86400 * 7)
            return Math.floor(s / 86400) + " 天前";
        return Qt.formatDate(then, "yyyy-MM-dd");
    }

    function startOfDay(date: var): var {
        const d = new Date(date);
        d.setHours(0, 0, 0, 0);
        return d;
    }

    // Whole days between the date and today (0 = today).
    function daysAgo(iso: var): int {
        return Math.round((startOfDay(new Date()) - startOfDay(new Date(iso))) / 86400000);
    }

    // "今天" / "昨天" / "3 天前" / a date.
    function day(iso: var): string {
        if (!iso)
            return "暂无活动";
        const n = daysAgo(iso);
        return n <= 0 ? "今天" : n === 1 ? "昨天" : n < 7 ? n + " 天前" : Qt.formatDate(new Date(iso), "yyyy-MM-dd");
    }

    // Record time: "今天 09:42" / "昨天 18:20" / "3 天前" / a date.
    function when(iso: var): string {
        if (!iso)
            return "";
        const n = daysAgo(iso);
        return n <= 1 ? day(iso) + " " + Qt.formatTime(new Date(iso), "HH:mm") : day(iso);
    }

    // Items of a Markdown list ("- [x] done", "1. step"), or [] if the text is not a list.
    function listItems(markdown: string): var {
        const items = [];
        for (const line of markdown.split("\n")) {
            const m = line.match(/^\s*(?:[-*+]|\d+[.)])\s+(?:\[([ xX])\]\s+)?(.*)$/);
            if (m)
                items.push({ text: m[2].trim(), done: (m[1] ?? " ").toLowerCase() === "x" });
        }
        return items;
    }

    // Cut to `max` characters, the last one becoming an ellipsis (BarStyle.elide).
    function elide(text: string, max: int): string {
        const chars = Array.from(text);
        return chars.length > max ? chars.slice(0, max - 1).join("") + "…" : text;
    }

    // One-line preview of a Markdown body: drop fences, heading/list/quote markers and emphasis.
    function plain(markdown: string): string {
        return markdown
            .replace(/```\w*/g, " ")
            .replace(/^\s{0,3}(#{1,6}|>|[-*+]|\d+\.)\s+/gm, "")
            .replace(/[`*~]+/g, "")
            .replace(/(^|\s)_{1,2}(\S[^_]*?)_{1,2}(?=\s|$)/g, "$1$2")   // _emphasis_, not snake_case
            .replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1")
            .replace(/\s+/g, " ")
            .trim();
    }

    function home(path: string): string {
        const h = Quickshell.env("HOME");
        return h && path.startsWith(h + "/") ? "~" + path.slice(h.length) : path;
    }

    FileView {
        path: root.themePath
        watchChanges: true
        printErrors: false
        onFileChanged: reload()
        onLoaded: {
            try {
                root.theme = JSON.parse(text());
            } catch (e) {
                console.warn("theme.json:", e);
            }
        }
    }
}
