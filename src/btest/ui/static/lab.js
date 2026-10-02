// Strategy lab: file tree, editor tabs, run and sweep forms, job output.

const store = {
    get(key, fallback) {
        try {
            const v = localStorage.getItem("btest." + key);
            return v == null ? fallback : JSON.parse(v);
        } catch { return fallback; }
    },
    set(key, value) {
        try { localStorage.setItem("btest." + key, JSON.stringify(value)); } catch { /* private mode */ }
    },
};

// Unsaved edits survive switching tabs and reloading, like an editor's hot exit.
const drafts = new Map(Object.entries(store.get("drafts", {})).map(([k, v]) => [+k, v]));
const saveDrafts = () => store.set("drafts", Object.fromEntries(drafts));
let tabs = store.get("tabs", []);
const expanded = new Set(store.get("expanded", []));
const pollers = new Map();
let labConfig = null;
let page = 0;
let quickOpen = null;
let keysInstalled = false;
let current = null;

const leaf = name => name.split("/").pop();
// Strategies get a "py" badge; indicators a curve glyph, so the tabs tell them apart.
const kindIcon = kind => {
    const e = document.createElement("span");
    e.className = kind === "indicator" ? "ico ind" : "ico py";
    e.setAttribute("aria-hidden", "true");
    e.textContent = kind === "indicator" ? "∿" : "py";
    return e;
};
const folderOf = name => name.split("/").slice(0, -1).join("/");

function parseValue(raw) {
    const t = String(raw).trim();
    if (t === "") return undefined;
    try { return JSON.parse(t); } catch { return t; }
}
const showValue = v => (typeof v === "string" ? v : JSON.stringify(v));

function gridCount(text) {
    const t = text.trim();
    if (!t) return 1;
    const parts = t.split(":");
    if (parts.length === 3 && parts.every(p => p.trim() !== "" && !isNaN(+p))) {
        const [a, b, step] = parts.map(Number);
        return step > 0 && b >= a ? Math.floor((b - a) / step + 1e-9) + 1 : 0;
    }
    return t.split(",").filter(x => x.trim()).length;
}

export async function labPage(id, ui) {
    const {h, api, write, pct, num, int, tone, onMount, lineChart} = ui;
    const token = ++page;
    labConfig = labConfig || await api("/api/lab");
    let list = await api("/api/strategies");

    if (!id) {
        const last = store.get("last", null);
        const pick = list.find(s => s.id === last) || list[0];
        if (pick) {
            location.replace(`#/strategies/${pick.id}`);
            return [];
        }
    }
    let s = id ? await api(`/api/strategies/${id}`).catch(e => {
        if (e.status === 404) {
            tabs = tabs.filter(t => t !== id);
            store.set("tabs", tabs);
            return null;
        }
        throw e;
    }) : null;
    if (id && !s) {
        location.replace("#/strategies");
        return [];
    }
    if (s) {
        store.set("last", s.id);
        if (!tabs.includes(s.id)) tabs.push(s.id);
        store.set("tabs", tabs);
        expandTo(s.name, s.kind);
    }

    // ---------- explorer ----------

    const treeEl = h("div", {class: "tree", role: "tree", "aria-label": "Strategies"});
    const filterEl = h("input", {class: "filter", type: "search", placeholder: "Filter",
                                 "aria-label": "Filter strategies", oninput: () => renderTree()});
    const newRow = h("div");

    // Folder keys carry the kind, so a strategy folder and an indicator folder with the same
    // name open and close separately.
    function expandTo(name, kind) {
        const parts = name.split("/");
        for (let i = 1; i < parts.length; i++) expanded.add(`${kind}:${parts.slice(0, i).join("/")}`);
        store.set("expanded", [...expanded]);
    }

    function buildTree(items) {
        const root = {folders: new Map(), files: []};
        for (const it of items) {
            const parts = it.name.split("/");
            let node = root, path = "";
            for (const p of parts.slice(0, -1)) {
                path = path ? path + "/" + p : p;
                if (!node.folders.has(p)) node.folders.set(p, {path, folders: new Map(), files: []});
                node = node.folders.get(p);
            }
            node.files.push(it);
        }
        return root;
    }

    function fileRow(it, depth) {
        const active = s && it.id === s.id;
        const dirty = drafts.has(it.id);
        const row = h("div", {class: "node file" + (active ? " active" : ""), role: "treeitem",
                              tabindex: active ? 0 : -1, "aria-selected": String(!!active),
                              style: `--d:${depth}`, "data-id": it.id,
                              onclick: ev => { if (!ev.target.closest("button,input")) go(it.id); },
                              onkeydown: ev => treeKeys(ev, it)},
            kindIcon(it.kind),
            h("span", {class: "label"}, leaf(it.name)),
            dirty ? h("span", {class: "dot", title: "Unsaved changes"}) : null,
            h("span", {class: "ver"}, "v" + it.version),
            h("span", {class: "acts"},
              h("button", {class: "icon", title: "Rename (F2)", "aria-label": `Rename ${it.name}`,
                           onclick: () => startRename(row, it)}, "✎"),
              h("button", {class: "icon", title: "Delete", "aria-label": `Delete ${it.name}`,
                           onclick: () => confirmDelete(row, it)}, "×")));
        return row;
    }

    const SECTIONS = [["strategy", "Strategies", "New strategy"], ["indicator", "Indicators", "New indicator"]];
    let creating = null;

    function renderTree() {
        const q = filterEl.value.trim().toLowerCase();
        const rows = [];
        for (const [kind, title, addLabel] of SECTIONS) {
            const items = list.filter(it => it.kind === kind && (!q || it.name.includes(q)));
            rows.push(h("div", {class: "ex-section"}, h("span", {}, title),
                h("button", {class: "icon", title: addLabel, "aria-label": addLabel, onclick: () => showNewRow(kind)}, "+")));
            if (creating === kind) rows.push(newRow);
            const walk = (node, depth) => {
                for (const [name, f] of [...node.folders].sort((a, b) => a[0].localeCompare(b[0]))) {
                    const key = `${kind}:${f.path}`;
                    const open = q || expanded.has(key);
                    rows.push(h("div", {class: "node folder", role: "treeitem", "aria-expanded": String(!!open),
                                        tabindex: -1, style: `--d:${depth}`,
                                        onclick: () => toggle(key),
                                        onkeydown: ev => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); toggle(key); } else treeKeys(ev, null); }},
                        h("span", {class: "chev", "aria-hidden": "true"}, open ? "▾" : "▸"),
                        h("span", {class: "label"}, name)));
                    if (open) walk(f, depth + 1);
                }
                for (const it of node.files.sort((a, b) => a.name.localeCompare(b.name))) rows.push(fileRow(it, depth));
            };
            const before = rows.length;
            walk(buildTree(items), 0);
            if (rows.length === before && creating !== kind) {
                rows.push(h("div", {class: "tree-empty"}, q ? "Nothing matches." : kind === "strategy"
                    ? "No strategies yet." : "No indicators yet. + makes one from an RSI template."));
            }
        }
        treeEl.replaceChildren(...rows);
    }

    function toggle(path) {
        if (expanded.has(path)) expanded.delete(path);
        else expanded.add(path);
        store.set("expanded", [...expanded]);
        renderTree();
    }

    function treeKeys(ev, it) {
        const rows = [...treeEl.querySelectorAll(".node")];
        const i = rows.indexOf(ev.currentTarget);
        if (ev.key === "ArrowDown" && rows[i + 1]) { ev.preventDefault(); rows[i + 1].focus(); }
        else if (ev.key === "ArrowUp" && rows[i - 1]) { ev.preventDefault(); rows[i - 1].focus(); }
        else if (ev.key === "Enter" && it) go(it.id);
        else if (ev.key === "F2" && it) startRename(ev.currentTarget, it);
    }

    function startRename(row, it) {
        const input = h("input", {class: "inline", value: it.name, "aria-label": "New name"});
        const err = h("div", {class: "inline-err"});
        const done = async commit => {
            if (!commit) return renderTree();
            try {
                await write("PATCH", `/api/strategies/${it.id}`, {name: input.value});
                list = await api("/api/strategies");
                if (s && s.id === it.id) {
                    s.name = list.find(x => x.id === it.id)?.name || s.name;
                    expandTo(s.name, s.kind);
                    renderHeader();
                }
                renderTree();
                renderTabs();
            } catch (e) { err.textContent = e.message; input.focus(); }
        };
        input.addEventListener("keydown", ev => {
            if (ev.key === "Enter") done(true);
            if (ev.key === "Escape") done(false);
        });
        row.replaceChildren(input, err);
        input.focus();
        input.setSelectionRange(input.value.length - leaf(it.name).length, input.value.length);
    }

    function confirmDelete(row, it) {
        row.replaceChildren(h("span", {class: "label"}, `Delete ${leaf(it.name)}?`),
            h("button", {class: "mini danger", onclick: async () => {
                await write("DELETE", `/api/strategies/${it.id}`);
                drafts.delete(it.id);
                saveDrafts();
                tabs = tabs.filter(t => t !== it.id);
                store.set("tabs", tabs);
                if (s && s.id === it.id) location.hash = "#/strategies";
                else { list = await api("/api/strategies"); renderTree(); renderTabs(); }
            }}, "Delete"),
            h("button", {class: "mini", onclick: () => renderTree()}, "Cancel"));
        row.querySelector("button.danger").focus();
    }

    function showNewRow(kind = "strategy") {
        const prefix = s && s.kind === kind && folderOf(s.name) ? folderOf(s.name) + "/" : "";
        const input = h("input", {class: "inline", value: prefix, placeholder: "folder/name",
                                  "aria-label": `New ${kind} name`});
        const err = h("div", {class: "inline-err"});
        input.addEventListener("keydown", async ev => {
            if (ev.key === "Escape") { creating = null; renderTree(); }
            if (ev.key !== "Enter") return;
            try {
                const r = await write("POST", "/api/strategies", {name: input.value, kind});
                creating = null;
                go(r.id);
            } catch (e) { err.textContent = e.message; }
        });
        newRow.replaceChildren(h("div", {class: "node new"}, input), err);
        creating = kind;
        renderTree();
        input.focus();
    }

    const explorer = h("aside", {class: "explorer"},
        h("div", {class: "ex-filter", style: "padding-top:10px"}, filterEl), treeEl,
        h("div", {class: "ex-foot"}, h("kbd", {}, navigator.platform.includes("Mac") ? "⌘P" : "Ctrl+P"), " to jump to any file"));

    function go(sid) {
        location.hash = `#/strategies/${sid}`;
    }

    renderTree();

    if (!s) {
        return [h("div", {class: "lab"}, explorer, h("section", {class: "lab-main"},
            h("div", {class: "empty", style: "margin:auto"},
              h("p", {}, "Create a strategy to start. It opens with a buy-and-hold template you can edit."),
              h("button", {class: "primary", onclick: () => showNewRow("strategy")}, "New strategy"),
              h("p", {style: "margin-top:18px"}, "Or add the files in strategies/ from the terminal:"),
              h("code", {}, "uv run btest import-strategies"))))];
    }

    // ---------- editor ----------

    const tabsEl = h("div", {class: "tabsbar", role: "tablist"});
    const crumbEl = h("div", {class: "crumb"});
    const versionSel = h("select", {"aria-label": "Version"});
    const saveBtn = h("button", {onclick: () => save()}, "Save");
    const runBtn = h("button", {class: "primary", onclick: () => submit("run")}, "Run");
    const bannerEl = h("div");
    const editorEl = h("div", {class: "editor"});
    const outputEl = h("div", {class: "output-body"});
    const historyEl = h("div", {class: "history"});
    let cm = null;
    let viewing = null;
    let errorMark = null;

    const isDirty = () => drafts.has(s.id);

    function renderTabs() {
        const named = new Map(list.map(it => [it.id, it]));
        tabs = tabs.filter(t => named.has(t));
        store.set("tabs", tabs);
        tabsEl.replaceChildren(...tabs.map(t => {
            const it = named.get(t);
            const active = t === s.id;
            return h("div", {class: "tab" + (active ? " active" : ""), role: "tab", "aria-selected": String(active),
                             title: it.name, tabindex: 0,
                             onclick: ev => { if (!ev.target.closest("button")) go(t); },
                             onkeydown: ev => { if (ev.key === "Enter") go(t); },
                             onauxclick: ev => { if (ev.button === 1) closeTab(t); }},
                kindIcon(it.kind), leaf(it.name),
                h("button", {class: "close" + (drafts.has(t) ? " dirty" : ""), "aria-label": `Close ${it.name}`,
                             title: drafts.has(t) ? "Unsaved changes are kept" : "Close",
                             onclick: () => closeTab(t)}, drafts.has(t) ? "●" : "×"));
        }));
    }

    function closeTab(t) {
        const i = tabs.indexOf(t);
        tabs = tabs.filter(x => x !== t);
        store.set("tabs", tabs);
        if (t === s.id) {
            const next = tabs[Math.min(i, tabs.length - 1)];
            if (next) go(next);
            else { store.set("last", null); location.hash = "#/runs"; }
        } else renderTabs();
    }

    function renderHeader() {
        const parts = s.name.split("/");
        crumbEl.replaceChildren(...parts.flatMap((p, i) => [
            i ? h("span", {class: "sep"}, "/") : null,
            h("span", {class: i === parts.length - 1 ? "leaf" : ""}, i === parts.length - 1 ? p + ".py" : p)])
            .filter(Boolean));
        versionSel.replaceChildren(...s.versions.map(v => h("option", {value: v.version, selected: v.version === (viewing?.version || s.latest)},
            `v${v.version}${v.version === s.latest ? " (latest)" : ""}  ${v.created_at.slice(0, 16).replace("T", " ")}`)));
        saveBtn.disabled = !isDirty() || !!viewing;
        saveBtn.textContent = isDirty() ? "Save" : "Saved";
    }

    versionSel.addEventListener("change", async () => {
        const v = +versionSel.value;
        if (v === s.latest) return showLatest();
        viewing = await api(`/api/strategies/${s.id}?version=${v}`);
        cm.setValue(viewing.code);
        cm.setOption("readOnly", true);
        bannerEl.replaceChildren(h("div", {class: "banner"},
            `Viewing v${v}, read-only.`,
            h("button", {class: "mini", onclick: () => {
                const code = viewing.code;
                showLatest();
                cm.setValue(code);
            }}, "Restore as a new version"),
            h("button", {class: "mini", onclick: showLatest}, "Back to latest")));
        renderHeader();
    });

    function showLatest() {
        viewing = null;
        cm.setOption("readOnly", false);
        cm.setValue(drafts.get(s.id)?.code ?? s.code);
        bannerEl.replaceChildren();
        renderHeader();
        cm.focus();
    }

    function markError(line) {
        clearError();
        if (!line || !cm) return;
        errorMark = cm.addLineClass(line - 1, "background", "cm-error-line");
        cm.scrollIntoView({line: line - 1, ch: 0}, 120);
    }
    function clearError() {
        if (errorMark) cm.removeLineClass(errorMark, "background", "cm-error-line");
        errorMark = null;
    }
    function jumpTo(line) {
        cm.focus();
        cm.setCursor({line: line - 1, ch: 0});
        markError(line);
    }

    // Saves run one at a time; a second Cmd+S while one is in flight waits for it, so it
    // builds on the new version instead of being refused as stale.
    let saving = Promise.resolve();
    function save() {
        const next = saving.then(saveNow, saveNow);
        saving = next.catch(() => {});
        return next;
    }

    async function saveNow() {
        if (viewing) return s;
        if (!isDirty()) return s;
        const code = cm.getValue();
        try {
            const next = await write("PUT", `/api/strategies/${s.id}`, {code, base_version: s.latest});
            s = next;
            drafts.delete(s.id);
            saveDrafts();
            list = await api("/api/strategies");
            renderTree();
            renderTabs();
            renderHeader();
            if (s.kind === "indicator") {
                renderIndInfo();
                if (!s.parse_error && preview) preview.updateCustom(s.id, s);
            } else renderForm();
            if (s.parse_error) {
                showOutput(errorBox(s.parse_error, s.parse_error_line, null));
                markError(s.parse_error_line);
            }
            return s;
        } catch (e) {
            showOutput(errorBox(e.message, null, null, e.status === 409 ? h("button", {class: "mini", onclick: async () => {
                const latest = await api(`/api/strategies/${s.id}`);
                drafts.set(s.id, {code: cm.getValue()});
                s = latest;
                renderHeader();
                showOutput(h("p", {class: "muted"}, `Loaded v${s.latest}. Your edits are still in the editor; save again to put them on top.`));
            }}, "Load the newer version") : null));
            throw e;
        }
    }

    // ---------- run form ----------

    const formKey = `form.${s.id}`;
    const form = store.get(formKey, {});
    const saveForm = () => store.set(formKey, form);
    const formEl = h("div", {class: "runform"});
    const sweepEl = h("div", {class: "runform"});
    const holdoutAt = labConfig.holdout_start;

    function field(label, input, hint) {
        return h("label", {class: "fld"}, h("span", {}, label), input, hint ? h("small", {}, hint) : null);
    }

    function renderForm() {
        form.symbols = form.symbols || [typeof s.params.symbol === "string" && labConfig.symbols.includes(s.params.symbol) ? s.params.symbol : "SPY"];
        form.start = form.start || labConfig.history_start;
        form.end = form.end || labConfig.holdout_start;
        form.params = form.params || {};
        form.config = form.config || {};
        form.grid = form.grid || {};
        const holdoutRow = h("label", {class: "check warn"});
        const updHoldout = () => {
            const reaches = form.end > holdoutAt;
            holdoutRow.style.display = reaches ? "" : "none";
            holdoutRow.replaceChildren(h("input", {type: "checkbox", checked: !!form.spend_holdout, onchange: ev => {
                form.spend_holdout = ev.target.checked; saveForm();
            }}), ` Use the holdout (data from ${holdoutAt}). Each look spends some of its value as a clean test.`);
        };
        const date = key => h("input", {type: "date", value: form[key], min: labConfig.history_start,
                                         oninput: ev => { form[key] = ev.target.value; saveForm(); updHoldout(); }});
        const params = Object.entries(s.params);
        formEl.replaceChildren(
            h("div", {class: "fld"}, h("span", {}, "Symbols"), h("div", {class: "chips"}, labConfig.symbols.map(sym =>
                h("label", {class: "chip"}, h("input", {type: "checkbox", checked: form.symbols.includes(sym), onchange: ev => {
                    form.symbols = ev.target.checked ? [...new Set([...form.symbols, sym])] : form.symbols.filter(x => x !== sym);
                    saveForm();
                }}), sym)))),
            h("div", {class: "row2"}, field("From", date("start")), field("Until", date("end"))),
            holdoutRow,
            params.length ? h("div", {class: "fld"}, h("span", {}, "Params"), h("div", {class: "params"}, params.map(([k, v]) =>
                h("label", {class: "param"}, h("span", {}, k), h("input", {
                    value: k in form.params ? showValue(form.params[k]) : "", placeholder: showValue(v), spellcheck: "false",
                    oninput: ev => {
                        const val = parseValue(ev.target.value);
                        if (val === undefined) delete form.params[k]; else form.params[k] = val;
                        saveForm();
                    }}))))) : h("p", {class: "muted"}, "No params dict in this strategy."),
            h("details", {class: "costs"}, h("summary", {}, "Costs and cash"),
              h("div", {class: "row2"},
                ...[["cash", "Cash"], ["slippage_bps", "Slippage, bps"], ["commission_per_share", "Commission per share"], ["sec_fee_rate", "SEC fee rate"]].map(([k, label]) =>
                    field(label, h("input", {type: "number", step: "any", min: 0, value: form.config[k] ?? "", placeholder: labConfig.defaults[k],
                                             oninput: ev => { if (ev.target.value === "") delete form.config[k]; else form.config[k] = +ev.target.value; saveForm(); }})))),
              h("label", {class: "check"}, h("input", {type: "checkbox", checked: !!form.config.allow_short, onchange: ev => {
                  form.config.allow_short = ev.target.checked; saveForm();
              }}), " Allow short selling")),
            h("div", {class: "actions"}, runBtn, h("small", {class: "muted"}, navigator.platform.includes("Mac") ? "⌘↵" : "Ctrl+Enter")));
        updHoldout();

        const numeric = params.filter(([, v]) => typeof v === "number");
        const countEl = h("small", {class: "muted"});
        const updCount = () => {
            const n = numeric.reduce((acc, [k]) => acc * gridCount(form.grid[k] || ""), 1);
            const any = numeric.some(([k]) => (form.grid[k] || "").trim());
            countEl.textContent = any ? `${int(n)} combinations` : "Give at least one param a list of values.";
        };
        sweepEl.replaceChildren(
            !s.has_signals ? h("p", {class: "muted"}, "Sweeps use the fast path. Add a signals() method to this strategy to enable them.") :
            !numeric.length ? h("p", {class: "muted"}, "No numeric params to sweep.") :
            h("div", {},
              field("Symbol", h("select", {onchange: ev => { form.sweepSymbol = ev.target.value; saveForm(); }},
                  labConfig.symbols.map(sym => h("option", {selected: sym === (form.sweepSymbol || form.symbols[0])}, sym)))),
              h("div", {class: "params"}, numeric.map(([k, v]) => h("label", {class: "param"}, h("span", {}, k), h("input", {
                  value: form.grid[k] || "", placeholder: `${v} or 5,10,20 or 10:100:10`, spellcheck: "false",
                  oninput: ev => { form.grid[k] = ev.target.value; saveForm(); updCount(); }})))),
              h("p", {class: "muted"}, `Uses From and Until above; stops before the holdout (${holdoutAt}).`),
              h("div", {class: "actions"}, h("button", {onclick: () => submit("sweep")}, "Sweep"), countEl)));
        if (s.has_signals && numeric.length) updCount();
    }

    // ---------- jobs ----------

    function showOutput(...nodes) { outputEl.replaceChildren(...nodes); }

    function errorBox(message, line, log, extra) {
        return h("div", {class: "err-box"},
            h("div", {class: "err-msg"}, message),
            h("div", {class: "err-acts"}, line ? h("button", {class: "mini", onclick: () => jumpTo(line)}, `Go to line ${line}`) : null, extra),
            log ? h("details", {}, h("summary", {}, "Output"), h("pre", {}, log)) : null);
    }

    async function submit(kind) {
        if (viewing) showLatest();
        let cur;
        try { cur = await save(); } catch { return; }
        if (cur.parse_error) return;
        if (s.kind === "indicator") {
            indErrEl.replaceChildren();
            if (preview) preview.updateCustom(s.id, s);
            return;
        }
        clearError();
        const spec = kind === "run"
            ? {symbols: form.symbols, start: form.start, end: form.end, params: form.params, config: form.config, spend_holdout: !!form.spend_holdout}
            : {symbol: form.sweepSymbol || form.symbols[0], start: form.start, end: form.end > holdoutAt ? holdoutAt : form.end,
               params: form.params, config: form.config, grid: Object.fromEntries(Object.entries(form.grid).filter(([, v]) => v.trim()))};
        try {
            const r = await write("POST", "/api/jobs", {strategy_id: s.id, kind, version: cur.latest, spec});
            pollers.set(s.id, r.id);
            follow(r.id);
        } catch (e) {
            showOutput(errorBox(e.message, null, null));
        }
    }

    async function follow(jid) {
        const mine = token;
        while (mine === page) {
            let j;
            try { j = await api(`/api/jobs/${jid}`); } catch (e) { showOutput(errorBox(e.message)); return; }
            if (mine !== page) return;
            renderJob(j);
            if (j.status === "done" || j.status === "failed") {
                pollers.delete(j.strategy_id);
                loadHistory();
                return;
            }
            await new Promise(r => setTimeout(r, 900));
        }
    }

    function elapsed(a, b) {
        const ms = (b ? new Date(b) : new Date()) - new Date(a);
        return (ms / 1000).toFixed(ms < 10000 ? 1 : 0) + " s";
    }

    async function renderJob(j) {
        const what = j.kind === "run" ? `Run of v${j.version}` : `Sweep of v${j.version}`;
        if (j.status === "queued") {
            showOutput(h("div", {class: "status-line"}, h("span", {class: "spin"}), `${what} is waiting for the worker`,
                       j.ahead ? ` (${j.ahead} ahead)` : "", "."));
        } else if (j.status === "running") {
            showOutput(h("div", {class: "status-line"}, h("span", {class: "spin"}), `${what} running, ${elapsed(j.started_at)}.`));
        } else if (j.status === "failed") {
            showOutput(h("div", {class: "status-line bad"}, `${what} failed after ${elapsed(j.started_at || j.created_at, j.finished_at)}.`),
                       errorBox(j.error, j.error_line, j.log));
            if (j.error_line && j.version === s.latest && !viewing) markError(j.error_line);
        } else if (j.kind === "sweep") {
            showOutput(h("div", {class: "status-line good"}, `${what} finished in ${elapsed(j.started_at, j.finished_at)}.`),
                       h("a", {class: "mini-link", href: `#/sweeps/${j.sweep_id}`}, `Open the parameter map for sweep ${j.sweep_id}`));
        } else {
            const r = await api(`/api/runs/${j.run_id}`);
            const M = r.metrics, B = r.benchmark;
            const chartEl = h("div", {class: "chart"});
            showOutput(
                h("div", {class: "status-line good"}, `${what} finished in ${elapsed(j.started_at, j.finished_at)}.`,
                  h("a", {class: "mini-link", href: `#/runs/${r.id}`}, `Open run ${r.id}`)),
                h("div", {class: "minifigs"},
                  ...[["Return", pct(M.total_return, 1), tone(M.total_return), pct(B.total_return, 1)],
                      ["CAGR", pct(M.cagr), tone(M.cagr), pct(B.cagr)],
                      ["Sharpe", num(M.sharpe), "", num(B.sharpe)],
                      ["Max DD", pct(M.max_drawdown), "", pct(B.max_drawdown)],
                      ["Fills", int(M.fills), "", null]].map(([label, v, cls, b]) =>
                      h("div", {}, h("span", {}, label), h("b", {class: cls}, v), b ? h("small", {}, "SPY " + b) : h("small", {}, " ")))),
                chartEl);
            requestAnimationFrame(() => lineChart(chartEl, {
                dates: r.equity.map(e => e[0]), height: 130, fmt: ui.money, tickFmt: v => "$" + Math.round(v / 1e3) + "k",
                label: "Equity of this run against SPY",
                series: [{name: "Strategy", values: r.equity.map(e => e[1]), color: "var(--s1)"},
                         {name: "SPY", values: r.equity.map(e => e[2]), color: "var(--dim)", width: 1.5}]}));
        }
    }

    async function loadHistory() {
        const jobs = await api(`/api/strategies/${s.id}/jobs`);
        if (!jobs.length) {
            historyEl.replaceChildren(h("p", {class: "muted"}, "No runs of this strategy yet."));
            return;
        }
        historyEl.replaceChildren(h("table", {},
            h("thead", {}, h("tr", {}, h("th", {}, "Ver"), h("th", {}, "Window"),
              h("th", {class: "n"}, "Sharpe"), h("th", {class: "n"}, "CAGR"), h("th", {class: "n"}, "Max DD"))),
            h("tbody", {}, jobs.map(j => h("tr", {class: "link", onclick: () => {
                if (j.run_id) location.hash = `#/runs/${j.run_id}`;
                else if (j.sweep_id) location.hash = `#/sweeps/${j.sweep_id}`;
                else renderJob(j.status === "failed" ? {...j, started_at: j.created_at} : j);
            }},
                h("td", {class: "num", title: `Job ${j.id}`}, "v" + j.version),
                h("td", {class: "num"}, `${j.spec.start.slice(0, 4)}–${j.spec.end.slice(0, 4)}`),
                j.kind === "sweep" || j.status !== "done"
                    ? h("td", {colspan: 3, class: "n"}, h("span", {class: "flag" + (j.status === "failed" ? " bad" : " quiet")},
                        j.status === "done" ? "sweep" : j.status))
                    : [h("td", {class: "n"}, num(j.sharpe)),
                       h("td", {class: "n " + tone(j.cagr)}, pct(j.cagr)),
                       h("td", {class: "n"}, pct(j.max_drawdown))])))));
    }

    // ---------- indicator preview ----------

    const indErrEl = h("div");
    const indInfoEl = h("div", {class: "runform"});
    let preview = null;

    function renderIndInfo() {
        const params = Object.entries(s.params);
        indInfoEl.replaceChildren(
            h("p", {class: "muted"}, "Saving redraws the preview below. Add it to any chart from the Add indicator menu."),
            h("dl", {class: "kv"},
              h("dt", {}, "Class"), h("dd", {}, s.class_name || "–"),
              h("dt", {}, "Pane"), h("dd", {}, s.pane === "own" ? "its own, below volume" : "on the candles"),
              h("dt", {}, "Levels"), h("dd", {}, s.levels.length ? s.levels.join(", ") : "none"),
              h("dt", {}, "Params"), h("dd", {}, params.length ? params.map(([k, v]) => `${k}=${showValue(v)}`).join(", ") : "none")),
            h("p", {class: "muted"}, "compute(self, c) gets numpy arrays c[\"open\"], c[\"high\"], c[\"low\"], c[\"close\"], c[\"volume\"] and c[\"t\"] (UTC seconds) and returns {line_name: array}, one value per candle, NaN for none."),
            h("div", {class: "actions"}, runBtn, h("small", {class: "muted"}, navigator.platform.includes("Mac") ? "⌘↵" : "Ctrl+Enter")));
    }

    function showIndicatorError(err) {
        const b = err.body || {};
        indErrEl.replaceChildren(errorBox(b.error || err.message, b.error_line, b.log));
        if (b.error_line && !viewing) markError(b.error_line);
    }

    // ---------- layout ----------

    const isInd = s.kind === "indicator";
    if (isInd) runBtn.textContent = "Preview";
    const nodes = [h("div", {class: "lab"},
        explorer,
        h("section", {class: "lab-main"},
          tabsEl,
          h("div", {class: "toolbar"}, crumbEl, h("span", {class: "spacer"}), versionSel, saveBtn),
          bannerEl,
          editorEl,
          isInd
            ? h("div", {class: "output tall"}, h("div", {class: "output-head"}, "Preview"), h("div", {class: "output-body"}, indErrEl, outputEl))
            : h("div", {class: "output"}, h("div", {class: "output-head"}, "Output"), outputEl)),
        isInd
          ? h("aside", {class: "lab-side"}, h("section", {}, h("h3", {}, "Indicator"), indInfoEl))
          : h("aside", {class: "lab-side"},
              h("section", {}, h("h3", {}, "Run"), formEl),
              h("details", {class: "sweep", open: store.get("sweepOpen", false), ontoggle: ev => store.set("sweepOpen", ev.target.open)},
                h("summary", {}, h("h3", {}, "Sweep")), sweepEl),
              h("section", {}, h("h3", {}, "History"), historyEl)))];

    renderTabs();
    renderHeader();
    if (isInd) renderIndInfo();
    else {
        renderForm();
        showOutput(h("p", {class: "muted"}, "Run results and errors appear here."));
    }

    onMount(() => {
        cm = window.CodeMirror(editorEl, {
            value: drafts.get(s.id)?.code ?? s.code,
            mode: "python", lineNumbers: true, indentUnit: 4, tabSize: 4, indentWithTabs: false,
            matchBrackets: true, autoCloseBrackets: true, styleActiveLine: true, viewportMargin: 40,
            extraKeys: {
                Tab: c => (c.somethingSelected() ? c.indentSelection("add") : c.replaceSelection("    ", "end")),
                "Shift-Tab": c => c.indentSelection("subtract"),
                "Cmd-/": "toggleComment", "Ctrl-/": "toggleComment",
            },
        });
        cm.on("change", () => {
            if (viewing) return;
            clearError();
            const code = cm.getValue();
            if (code === s.code) drafts.delete(s.id);
            else drafts.set(s.id, {code});
            saveDrafts();
            renderHeader();
            const dot = treeEl.querySelector(`[data-id="${s.id}"]`);
            if (dot && !!dot.querySelector(".dot") !== isDirty()) renderTree();
            const tabClose = tabsEl.querySelector(".tab.active .close");
            if (tabClose && tabClose.classList.contains("dirty") !== isDirty()) renderTabs();
        });
        if (s.parse_error) markError(s.parse_error_line);
        cm.focus();
        if (isInd) {
            import("/static/pricechart.js").then(({priceChart}) => {
                if (token !== page) return;
                outputEl.classList.add("pc");
                preview = priceChart(outputEl, {
                    symbol: "SPY", symbols: labConfig.symbols, tf: "15m", end: new Date().toISOString().slice(0, 10),
                    minDate: labConfig.history_start, visible: 200, storeKey: `preview.${s.id}`, freshIndicators: true,
                    lockCustom: s.id,
                    indicators: [{type: "custom", id: s.id, name: s.name, params: {}, defaults: s.params, pane: s.pane, levels: s.levels}],
                    onIndicatorError: (id, err) => { if (id === s.id) showIndicatorError(err); },
                    onIndicatorOk: id => { if (id === s.id) { indErrEl.replaceChildren(); clearError(); } },
                }, ui);
                ui.addCleanup?.(preview.destroy);
            });
            treeEl.querySelector(".node.active")?.scrollIntoView({block: "nearest"});
            current = {submit, save: () => save().catch(() => {}), list: () => list};
            return;
        }
        const pending = pollers.get(s.id);
        if (pending) follow(pending);
        loadHistory();
        treeEl.querySelector(".node.active")?.scrollIntoView({block: "nearest"});
    });

    current = {submit, save: () => save().catch(() => {}), list: () => list};
    installKeys();
    return nodes;
}

function openQuick() {
    if (!current) return;
    const items = current.list();
    if (quickOpen) quickOpen.remove();
    const input = document.createElement("input");
    input.className = "quick-input";
    input.placeholder = "Go to strategy";
    input.setAttribute("aria-label", "Go to strategy");
    const listEl = document.createElement("div");
    listEl.className = "quick-list";
    listEl.setAttribute("role", "listbox");
    const box = document.createElement("div");
    box.className = "quick";
    box.append(input, listEl);
    const shade = document.createElement("div");
    shade.className = "quick-shade";
    shade.append(box);
    shade.addEventListener("mousedown", ev => { if (ev.target === shade) close(); });
    document.body.append(shade);
    quickOpen = shade;
    let sel = 0, shown = [];
    const score = (name, q) => {
        let i = 0, gaps = 0, last = -1;
        for (const ch of q) {
            const k = name.indexOf(ch, i);
            if (k < 0) return -1;
            if (last >= 0) gaps += k - last - 1;
            last = k; i = k + 1;
        }
        return gaps + (name.endsWith(q) ? -5 : 0);
    };
    function render() {
        const q = input.value.trim().toLowerCase();
        shown = items.map(it => [it, q ? score(it.name, q) : 0]).filter(([, sc]) => sc >= 0)
            .sort((a, b) => a[1] - b[1] || a[0].name.localeCompare(b[0].name)).map(([it]) => it).slice(0, 12);
        sel = Math.min(sel, Math.max(0, shown.length - 1));
        listEl.replaceChildren(...shown.map((it, i) => {
            const row = document.createElement("div");
            row.className = "quick-row" + (i === sel ? " sel" : "");
            row.setAttribute("role", "option");
            const a = document.createElement("b");
            a.textContent = leaf(it.name);
            const b = document.createElement("span");
            b.textContent = folderOf(it.name);
            row.append(a, b);
            row.addEventListener("mousedown", () => pick(it));
            return row;
        }));
        if (!shown.length) listEl.textContent = "No strategy matches.";
    }
    function pick(it) { close(); location.hash = `#/strategies/${it.id}`; }
    function close() { shade.remove(); quickOpen = null; }
    input.addEventListener("input", () => { sel = 0; render(); });
    input.addEventListener("keydown", ev => {
        if (ev.key === "ArrowDown") { ev.preventDefault(); sel = Math.min(sel + 1, shown.length - 1); render(); }
        else if (ev.key === "ArrowUp") { ev.preventDefault(); sel = Math.max(sel - 1, 0); render(); }
        else if (ev.key === "Enter" && shown[sel]) pick(shown[sel]);
        else if (ev.key === "Escape") close();
    });
    render();
    input.focus();
}

function installKeys() {
    if (keysInstalled) return;
    keysInstalled = true;
    document.addEventListener("keydown", ev => {
        if (!location.hash.startsWith("#/strategies") || !current) return;
        const mod = ev.metaKey || ev.ctrlKey;
        if (!mod) return;
        if (ev.key === "p" || ev.key === "P") { ev.preventDefault(); openQuick(); }
        else if (ev.key === "s" || ev.key === "S") { ev.preventDefault(); current.save(); }
        else if (ev.key === "Enter") { ev.preventDefault(); current.submit("run"); }
    });
}

export function leaveLab() {
    page++;
    current = null;
    if (quickOpen) { quickOpen.remove(); quickOpen = null; }
}
