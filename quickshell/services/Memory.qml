pragma Singleton

// Project data, read through the public ohmypm CLI (`--json`). Every call runs in its own
// process so overlapping requests never mix output; answers that arrive after a newer
// request for the same thing are dropped.

import QtQuick
import Quickshell
import Quickshell.Io

Singleton {
    id: root

    readonly property string bin: Quickshell.env("OHMYPM_BIN") || "ohmypm"
    readonly property string scripts: Quickshell.shellDir + "/scripts"

    property var projects: []
    property var openIssueItems: []      // open issue records of every project
    property var openIssues: ({})        // project id -> number of open issue records
    property var activity: []            // records of every project from the last 14 days, newest first
    property string selectedId: ""       // "" shows the dashboard
    property var details: ({})           // project id -> { context, recent, generation }
    property var entries: ({})           // "<project id>/<sequence>" -> full entry
    property string error: ""
    property bool loading: false
    property var refreshedAt: null
    property int generation: 0
    property string flash: ""            // short confirmation shown in the footer

    readonly property var selected: projects.find(p => p.id === selectedId) ?? null
    readonly property var detail: details[selectedId] ?? null
    readonly property bool onDashboard: selected === null

    property var focusDirs: []           // working directories of the focused window, see locate()

    // Records where the focused window is working (e.g. a terminal's cwd). Run it before
    // showing the panel: once mapped, the panel itself is the focused window.
    function locate(then: var): void {
        exec([scripts + "/focused-cwds.sh"], text => {
            focusDirs = text.split("\n").filter(Boolean);
            then();
        }, () => {
            focusDirs = [];
            then();
        });
    }

    // followFocus: select the project found by the last locate().
    function refresh(followFocus: bool): void {
        generation++;
        loading = true;
        let pending = 3;
        const done = () => {
            if (--pending > 0)
                return;
            loading = false;
            refreshedAt = new Date();
            const focused = followFocus ? projectFor(focusDirs) : null;
            if (focused)
                selectedId = focused.id;
            else if (!selected)
                selectedId = "";
            if (selectedId)
                loadDetail(selectedId);
        };
        call(["list"], data => {
            projects = data;
            error = "";
            done();
        }, message => {
            error = message;
            done();
        });
        call(["log", "list", "--all-projects", "--type", "issue", "--status", "open", "-n", "500"], data => {
            const counts = {};
            for (const e of data.items ?? [])
                counts[e.project_id] = (counts[e.project_id] ?? 0) + 1;
            openIssueItems = data.items ?? [];
            openIssues = counts;
            done();
        }, () => done());
        call(["log", "list", "--all-projects", "--since", "14d", "-r", "-n", "500"], data => {
            activity = data.items ?? [];
            done();
        }, () => done());
    }

    // Records per calendar day, oldest first: [{ date, counts: { type: n }, total }].
    function daily(items: var, days: int): var {
        const out = [];
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        for (let i = days - 1; i >= 0; i--) {
            const date = new Date(today);
            date.setDate(today.getDate() - i);
            out.push({ date, counts: {}, total: 0 });
        }
        for (const e of items) {
            const day = new Date(e.created_at);
            day.setHours(0, 0, 0, 0);
            const bucket = out[Math.round((day - out[0].date) / 86400000)];   // round: DST days
            if (!bucket)
                continue;
            bucket.counts[e.type] = (bucket.counts[e.type] ?? 0) + 1;
            bucket.total++;
        }
        return out;
    }

    function projectName(id: string): string {
        return projects.find(p => p.id === id)?.name ?? "";
    }

    // Longest registered root containing one of the directories.
    function projectFor(dirs: var): var {
        let best = null;
        for (const dir of dirs)
            for (const p of projects)
                if ((dir === p.root_path || dir.startsWith(p.root_path + "/")) && (!best || p.root_path.length > best.root_path.length))
                    best = p;
        return best;
    }

    // id "" opens the dashboard.
    function select(id: string): void {
        if (id === selectedId)
            return;
        selectedId = id;
        if (id)
            loadDetail(id);
    }

    // Walks dashboard, then the projects in list order.
    function step(delta: int): void {
        const ids = ["", ...projects.map(p => p.id)];
        const i = Math.max(0, ids.indexOf(selectedId));
        select(ids[(i + delta + ids.length) % ids.length]);
    }

    function loadDetail(id: string): void {
        const cached = details[id];
        if (cached && cached.generation === generation)
            return;
        const gen = generation;
        let context = null;
        let recent = null;
        let failure = "";
        let pending = 2;
        const done = () => {
            if (--pending > 0 || gen !== generation)
                return;
            const next = Object.assign({}, details);
            next[id] = { context, recent, error: failure, generation: gen };
            details = next;
        };
        const fail = message => {
            failure = message;
            done();
        };
        call(["context", "-p", id], data => {
            context = data;
            done();
        }, fail);
        call(["log", "list", "-p", id, "-r", "-n", "200"], data => {
            recent = data.items ?? [];
            done();
        }, fail);
    }

    function loadEntry(projectId: string, sequence: int): void {
        const key = projectId + "/" + sequence;
        call(["log", "show", String(sequence), "-p", projectId], data => {
            const next = Object.assign({}, entries);
            next[key] = data;
            entries = next;
        }, message => console.warn("ohmypm log show:", message));
    }

    // Full-text search inside one project; then(items) gets entry and summary hits.
    property int searchSerial: 0
    function search(projectId: string, query: string, then: var): void {
        const serial = ++searchSerial;
        call(["search", query, "-p", projectId, "-n", "30"], data => {
            if (serial === searchSerial)
                then(data.items ?? [], "");
        }, message => {
            if (serial === searchSerial)
                then([], message);
        });
    }

    function entry(projectId: string, sequence: int): var {
        return entries[projectId + "/" + sequence] ?? null;
    }

    // Actions on the selected project.
    function openTerminal(): void {
        if (selected)
            Quickshell.execDetached({ command: [Quickshell.env("TERMINAL") || "kitty"], workingDirectory: selected.root_path });
    }

    function openWeb(): void {
        Quickshell.execDetached([scripts + "/open-web.sh", ...(selected ? [selected.id] : [])]);
    }

    // Agent context on the clipboard, ready to paste into a new session.
    function copyContext(): void {
        if (!selected)
            return;
        const name = selected.name;
        exec(["sh", "-c", "\"$0\" context -p \"$1\" | wl-copy", bin, selected.id], () => showFlash("已复制 " + name + " 的上下文"), message => showFlash("复制失败：" + message));
    }

    function showFlash(text: string): void {
        flash = text;
        flashTimer.restart();
    }

    Timer {
        id: flashTimer
        interval: 2600
        onTriggered: root.flash = ""
    }

    // `ohmypm <args> --json`; onDone gets the parsed JSON, onFail a readable message.
    function call(args: var, onDone: var, onFail: var): void {
        exec([bin, ...args, "--json"], text => {
            try {
                onDone(JSON.parse(text));
            } catch (e) {
                onFail("无法解析 ohmypm 的输出");
            }
        }, onFail);
    }

    function exec(command: var, onDone: var, onFail: var): void {
        job.createObject(root, { command, whenDone: onDone, whenFailed: onFail }).running = true;
    }

    Component {
        id: job

        Process {
            id: proc
            property var whenDone
            property var whenFailed
            property bool started: false
            property int code: -1
            property int waiting: 3              // stdout, stderr, exit

            function settle(): void {
                if (--waiting > 0)
                    return;
                if (code === 0) {
                    whenDone(out.text);
                } else {
                    let message = err.text.trim();
                    try {
                        message = JSON.parse(message).error.message;
                    } catch (e) {}
                    whenFailed(message || "命令退出码 " + code);
                }
                destroy();
            }

            onStarted: started = true
            onRunningChanged: {
                // A missing binary never starts, so no streams or exit code follow.
                if (!running && !started) {
                    whenFailed("找不到命令 " + command[0]);
                    destroy();
                }
            }
            onExited: exitCode => {
                code = exitCode;
                settle();
            }
            stdout: StdioCollector {
                id: out
                onStreamFinished: proc.settle()
            }
            stderr: StdioCollector {
                id: err
                onStreamFinished: proc.settle()
            }
        }
    }
}
