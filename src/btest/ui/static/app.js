const view = document.getElementById("view");
const tip = document.getElementById("tip");
const NS = "http://www.w3.org/2000/svg";
const SERIES = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// ---------- formatting ----------

const MINUS = "−";
const sign = (v, s) => (v < 0 ? MINUS + s.replace("-", "") : s);
const pct = (v, d = 2) => (v == null ? "–" : sign(v, (v * 100).toFixed(d) + "%"));
const spct = (v, d = 2) => (v == null ? "–" : (v > 0 ? "+" : "") + pct(v, d));
const num = (v, d = 2) => (v == null ? "–" : sign(v, Math.abs(v).toLocaleString("en-US",
    {minimumFractionDigits: d, maximumFractionDigits: d})));
const int = v => (v == null ? "–" : Math.round(v).toLocaleString("en-US"));
// Share counts: whole numbers as is, fractional shares to three decimals.
const shares = v => (v == null ? "–" : v.toLocaleString("en-US", {maximumFractionDigits: 3}));
const money = v => (v == null ? "–" : sign(v, "$" + Math.abs(Math.round(v)).toLocaleString("en-US")));
const day = s => (s ? s.slice(0, 10) : "–");
const tone = v => (v == null || v === 0 ? "" : v > 0 ? "up" : "down");

const METRICS = {
    sharpe: {label: "Sharpe", fmt: v => num(v), better: "high"},
    cagr: {label: "CAGR", fmt: v => pct(v), better: "high", signed: true},
    total_return: {label: "Total return", fmt: v => pct(v, 1), better: "high", signed: true},
    max_drawdown: {label: "Max drawdown", fmt: v => pct(v), better: "high"},
    sortino: {label: "Sortino", fmt: v => num(v), better: "high"},
    ann_vol: {label: "Volatility", fmt: v => pct(v), better: "low"},
    exposure: {label: "Exposure", fmt: v => pct(v, 1)},
    fills: {label: "Fills", fmt: int, better: "low"},
    win_rate: {label: "Win rate", fmt: v => pct(v, 1), better: "high"},
    turnover: {label: "Turnover", fmt: v => num(v, 1) + "×", better: "low"},
    costs: {label: "Costs", fmt: money, better: "low"},
    end_equity: {label: "End equity", fmt: money, better: "high"},
};

// ---------- DOM helpers ----------

function h(tag, attrs = {}, ...kids) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
        if (v == null || v === false) continue;
        if (k === "class") e.className = v;
        else if (k === "style") e.style.cssText = v;
        else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
        else e.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) {
        if (kid == null || kid === false) continue;
        e.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    }
    return e;
}

function s(tag, attrs = {}, parent) {
    const e = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    if (parent) parent.appendChild(e);
    return e;
}

async function api(path) {
    const res = await fetch(path);
    if (res.status === 401) { location.href = "/login"; throw new Error("Signed out."); }
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
        const err = new Error(body.error || `${path} returned ${res.status}`);
        err.status = res.status;
        err.body = body;
        throw err;
    }
    return body;
}

async function write(method, path, payload) {
    const res = await fetch(path, {method, headers: {"Content-Type": "application/json", "X-Btest": "1"},
                                   body: payload === undefined ? undefined : JSON.stringify(payload)});
    if (res.status === 401) { location.href = "/login"; throw new Error("Signed out."); }
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
        const err = new Error(body.error || `${method} ${path} returned ${res.status}`);
        err.status = res.status;
        throw err;
    }
    return body;
}

function paramPills(params, hide = []) {
    return h("div", {class: "pills"}, Object.entries(params || {})
        .filter(([k]) => !hide.includes(k))
        .map(([k, v]) => h("span", {class: "pill"}, h("i", {}, k + " "),
                           typeof v === "string" ? v : JSON.stringify(v))));
}

function strategyName(s) {
    const [file, cls] = (s || "").split(":");
    return {file, cls: cls || file};
}

function showTip(x, y, title, rows) {
    tip.replaceChildren(h("div", {class: "t"}, title), ...rows.map(([label, value, color]) =>
        h("div", {class: "r"}, h("span", {style: color ? `--c:${color}` : ""}, label),
          h("b", {}, value))));
    tip.style.display = "block";
    const w = tip.offsetWidth, ht = tip.offsetHeight;
    const left = x + 16 + w > window.innerWidth ? x - w - 16 : x + 16;
    const top = Math.min(Math.max(8, y - ht / 2), window.innerHeight - ht - 8);
    tip.style.left = left + "px";
    tip.style.top = top + "px";
}
const hideTip = () => { tip.style.display = "none"; };

// ---------- charts ----------

function niceTicks(lo, hi, count) {
    if (hi === lo) { hi = lo + 1; }
    const raw = (hi - lo) / count;
    const mag = 10 ** Math.floor(Math.log10(raw));
    const step = [1, 2, 2.5, 5, 10].map(k => k * mag).find(x => x >= raw);
    const ticks = [];
    for (let k = Math.floor(lo / step); k <= Math.ceil(hi / step - 1e-9); k++) ticks.push(k * step + 0);
    return ticks;
}

function logTicks(lo, hi) {
    const out = [];
    for (let e = Math.floor(Math.log10(lo)); e <= Math.ceil(Math.log10(hi)); e++) {
        for (const m of [1, 2, 3, 5]) {
            const v = m * 10 ** e;
            if (v >= lo * 0.98 && v <= hi * 1.02) out.push(v);
        }
    }
    return out.length >= 2 ? out : [lo, hi];
}

// One crosshair shared by every chart in a group, so equity and drawdown read together.
function hoverGroup() {
    const charts = [];
    return {
        add(c) { charts.push(c); },
        move(i, source, ev) { charts.forEach(c => c.mark(i, c === source ? ev : null)); },
        leave() { charts.forEach(c => c.mark(null)); hideTip(); },
    };
}

function lineChart(el, o) {
    const dates = o.dates;
    const n = dates.length;
    let state = null;

    function draw() {
        el.replaceChildren();
        const W = Math.max(280, el.clientWidth);
        const H = o.height || 300;
        const labelled = o.endLabels && W > 560;
        const m = {l: 58, r: labelled ? 92 : 14, t: 10, b: 24};
        const vals = o.series.flatMap(sr => sr.values).filter(v => v != null && (!o.log || v > 0));
        let lo = Math.min(...vals), hi = Math.max(...vals);
        if (o.zeroTop) hi = 0;
        const ticks = o.log ? logTicks(lo, hi) : niceTicks(lo, hi, W < 500 ? 3 : 5);
        if (!o.log) { lo = ticks[0]; hi = ticks[ticks.length - 1]; }
        else { lo = Math.min(lo, ticks[0]); hi = Math.max(hi, ticks[ticks.length - 1]); }
        const f = o.log ? Math.log : v => v;
        const x = i => m.l + (W - m.l - m.r) * (n > 1 ? i / (n - 1) : 0);
        const y = v => m.t + (H - m.t - m.b) * (1 - (f(v) - f(lo)) / (f(hi) - f(lo)));
        const svg = s("svg", {viewBox: `0 0 ${W} ${H}`, height: H, role: "img",
                              "aria-label": o.label});
        for (const v of ticks) {
            s("line", {x1: m.l, x2: W - m.r, y1: y(v), y2: y(v), stroke: "var(--rule)"}, svg);
            const t = s("text", {x: m.l - 8, y: y(v) + 4, "text-anchor": "end",
                                 fill: "var(--faint)", "font-size": 11,
                                 "font-family": "var(--mono)"}, svg);
            t.textContent = (o.tickFmt || o.fmt)(v);
        }
        if (o.ref != null) {
            s("line", {x1: m.l, x2: W - m.r, y1: y(o.ref), y2: y(o.ref), stroke: "var(--rule-2)",
                       "stroke-dasharray": "3 3"}, svg);
        }
        let lastYear = null, lastX = -Infinity;
        dates.forEach((d, i) => {
            const yr = d.slice(0, 4);
            if (yr === lastYear) return;
            lastYear = yr;
            if (x(i) - lastX < 42) return;
            lastX = x(i);
            s("line", {x1: x(i), x2: x(i), y1: H - m.b, y2: H - m.b + 4, stroke: "var(--rule-2)"}, svg);
            const t = s("text", {x: x(i) + 3, y: H - 6, fill: "var(--faint)", "font-size": 11,
                                 "font-family": "var(--mono)"}, svg);
            t.textContent = yr;
        });
        s("line", {x1: m.l, x2: W - m.r, y1: H - m.b, y2: H - m.b, stroke: "var(--rule-2)"}, svg);
        const ends = [];
        // Draw the reference series first so the strategy line sits on top.
        [...o.series].reverse().forEach(sr => {
            let d = "", pen = false, last = null;
            sr.values.forEach((v, i) => {
                if (v == null || (o.log && v <= 0)) { pen = false; return; }
                d += (pen ? "L" : "M") + x(i).toFixed(1) + "," + y(v).toFixed(1);
                pen = true;
                last = [x(i), y(v)];
            });
            s("path", {d, fill: "none", stroke: sr.color, "stroke-width": sr.width || 2,
                       "stroke-dasharray": sr.dash || "none", "stroke-linejoin": "round"}, svg);
            if (labelled && last) ends.push({y: last[1], name: sr.name, color: sr.color});
        });
        // Nudge end labels apart so they never overlap.
        ends.sort((a, b) => a.y - b.y);
        for (let k = 1; k < ends.length; k++) ends[k].y = Math.max(ends[k].y, ends[k - 1].y + 15);
        for (const e of ends) {
            const t = s("text", {x: W - m.r + 8, y: e.y + 4, fill: "var(--dim)", "font-size": 12}, svg);
            t.textContent = e.name;
        }
        const cross = s("line", {y1: m.t, y2: H - m.b, stroke: "var(--dim)", "stroke-width": 1,
                                 "stroke-dasharray": "2 3", visibility: "hidden"}, svg);
        const dots = o.series.map(sr => s("circle", {r: 4, fill: sr.color, stroke: "var(--panel)",
                                                     "stroke-width": 2, visibility: "hidden"}, svg));
        const hit = s("rect", {x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b,
                               fill: "transparent"}, svg);
        el.appendChild(svg);
        state = {x, y, cross, dots, W, m};
        const idx = ev => {
            const r = svg.getBoundingClientRect();
            const px = (ev.clientX - r.left) / r.width * W;
            return Math.max(0, Math.min(n - 1, Math.round((px - m.l) / (W - m.l - m.r) * (n - 1))));
        };
        hit.addEventListener("pointermove", ev => o.group ? o.group.move(idx(ev), api_, ev)
                                                           : api_.mark(idx(ev), ev));
        hit.addEventListener("pointerleave", () => (o.group ? o.group.leave() : (api_.mark(null), hideTip())));
    }

    const api_ = {
        mark(i, ev) {
            if (!state) return;
            const {x, y, cross, dots} = state;
            if (i == null) {
                cross.setAttribute("visibility", "hidden");
                dots.forEach(d => d.setAttribute("visibility", "hidden"));
                return;
            }
            cross.setAttribute("x1", x(i));
            cross.setAttribute("x2", x(i));
            cross.setAttribute("visibility", "visible");
            o.series.forEach((sr, k) => {
                const v = sr.values[i];
                const ok = v != null && !(o.log && v <= 0);
                dots[k].setAttribute("visibility", ok ? "visible" : "hidden");
                if (ok) { dots[k].setAttribute("cx", x(i)); dots[k].setAttribute("cy", y(v)); }
            });
            if (ev) {
                showTip(ev.clientX, ev.clientY, dates[i],
                        o.series.map(sr => [sr.name, o.fmt(sr.values[i]), sr.color]));
            }
        },
        redraw: draw,
    };
    draw();
    if (o.group) o.group.add(api_);
    return api_;
}

// Colour ramps. Sequential: dark blue near the panel up to pale blue. Diverging: red, grey, blue.
const SEQ = ["#16243a", "#184f95", "#256abf", "#3987e5", "#6da7ec", "#b7d3f6"];
const NEG = "#e66767", MID = "#262e3b", POS = "#3987e5";

function hex(c) { return [1, 3, 5].map(k => parseInt(c.slice(k, k + 2), 16)); }
function mix(a, b, t) {
    const A = hex(a), B = hex(b);
    return "#" + A.map((v, k) => Math.round(v + (B[k] - v) * t).toString(16).padStart(2, "0")).join("");
}
function ramp(stops, t) {
    t = Math.max(0, Math.min(1, t));
    const p = t * (stops.length - 1), k = Math.min(stops.length - 2, Math.floor(p));
    return mix(stops[k], stops[k + 1], p - k);
}
function diverging(v, limit) {
    if (v == null) return "transparent";
    const t = Math.min(1, Math.abs(v) / limit);
    return mix(MID, v >= 0 ? POS : NEG, 0.15 + 0.85 * t);
}
function inkOn(bg) {
    const [r, g, b] = hex(bg);
    return 0.2126 * r + 0.7152 * g + 0.0722 * b > 140 ? "#0d1118" : "#e7ebf1";
}

// ---------- shared bits ----------

let refreshers = [];
// Disposers for widgets that hold resources (charts), run when the page changes.
let cleanups = [];
// Charts measure their container, so they draw only after the page is in the document.
let mounts = [];
const onMount = f => mounts.push(f);
let resizeTimer;
window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => refreshers.forEach(f => f()), 120);
});

function sortableTable(columns, rows, opts = {}) {
    let key = opts.sortKey, dir = opts.sortDir || -1;
    const table = h("table");
    const thead = h("thead");
    const tbody = h("tbody");
    table.append(thead, tbody);
    function render() {
        const sorted = key ? [...rows].sort((a, b) => {
            const col = columns.find(c => c.key === key);
            const va = col.value(a), vb = col.value(b);
            if (va == null) return 1;
            if (vb == null) return -1;
            return (va < vb ? -1 : va > vb ? 1 : 0) * dir;
        }) : rows;
        thead.replaceChildren(h("tr", {}, columns.map(c => h("th", {
            class: [c.numeric ? "n" : "", c.value ? "sortable" : ""].join(" "),
            "aria-sort": c.key === key ? (dir < 0 ? "descending" : "ascending") : null,
            tabindex: c.value ? 0 : null,
            onclick: c.value ? () => { dir = key === c.key ? -dir : -1; key = c.key; render(); } : null,
            onkeydown: c.value ? ev => { if (ev.key === "Enter") ev.target.click(); } : null,
        }, c.label))));
        tbody.replaceChildren(...sorted.map(r => {
            const tr = h("tr", {class: opts.rowClass ? opts.rowClass(r) : ""},
                         columns.map(c => h("td", {class: c.numeric ? "n " + (c.cls ? c.cls(r) : "") : c.tdClass || ""},
                                             c.cell(r))));
            if (opts.onRow) {
                tr.classList.add("link");
                tr.addEventListener("click", ev => {
                    if (ev.target.closest("input,button,a")) return;
                    opts.onRow(r);
                });
            }
            return tr;
        }));
    }
    render();
    table.rerender = render;
    return h("div", {class: "tablewrap"}, table);
}

function empty(msg, cmd) {
    return h("div", {class: "empty"}, msg, cmd ? h("div", {style: "margin-top:10px"}, h("code", {}, cmd)) : null);
}

// ---------- pages ----------

async function runsPage() {
    const runs = await api("/api/runs");
    const picked = new Set();
    const compareBtn = h("button", {class: "primary", disabled: true, onclick: () => {
        location.hash = "#/compare?ids=" + [...picked].join(",");
    }}, "Compare");
    const updateBtn = () => {
        compareBtn.disabled = picked.size < 2;
        compareBtn.textContent = picked.size >= 2 ? `Compare ${picked.size} runs` : "Compare";
    };
    const head = h("div", {class: "head"}, h("h1", {}, "Runs"),
                   h("span", {class: "count"}, `${runs.length}`), h("span", {class: "spacer"}),
                   runs.length > 1 ? compareBtn : null);
    if (!runs.length) {
        return [head, h("section", {class: "panel"}, empty("No backtests yet. Run one from the terminal:",
            "uv run btest run strategies/trend/ma_cross.py SPY --start 2016-01-01 --end 2025-01-01"))];
    }
    const m = k => r => r.metrics[k];
    let tableEl;
    const cols = [
        {key: "pick", label: "", cell: r => h("input", {type: "checkbox", "aria-label": `Select run ${r.id}`,
            onchange: ev => {
                if (ev.target.checked) {
                    if (picked.size >= 4) { ev.target.checked = false; return; }
                    picked.add(r.id);
                } else picked.delete(r.id);
                ev.target.closest("tr").classList.toggle("picked", ev.target.checked);
                updateBtn();
            }})},
        {key: "id", label: "Run", numeric: true, value: r => r.id, cell: r => r.id},
        {key: "strategy", label: "Strategy", value: r => r.strategy, tdClass: "strategy",
         cell: r => [strategyName(r.strategy).cls, h("small", {}, strategyName(r.strategy).file)]},
        {key: "edit", label: "", cell: r => r.strategy_id ? h("a", {class: "mini-link", href: `#/strategies/${r.strategy_id}`,
            title: "Open this strategy in the editor"}, "edit") : null},
        {key: "symbols", label: "Symbols", cell: r => r.symbols.join(" ")},
        {key: "tf", label: "Bars", value: r => r.timeframe, cell: r => h("span", {class: "num", style: "font-size:13px"}, r.timeframe)},
        {key: "window", label: "Window", value: r => r.start,
         cell: r => h("span", {class: "num", style: "font-size:13px"}, `${day(r.start)} to ${day(r.end)}`)},
        {key: "params", label: "Params", cell: r => paramPills(r.params, ["symbol"])},
        {key: "sharpe", label: "Sharpe", numeric: true, value: m("sharpe"), cell: r => num(r.metrics.sharpe)},
        {key: "cagr", label: "CAGR", numeric: true, value: m("cagr"), cell: r => pct(r.metrics.cagr),
         cls: r => tone(r.metrics.cagr)},
        {key: "max_drawdown", label: "Max DD", numeric: true, value: m("max_drawdown"),
         cell: r => pct(r.metrics.max_drawdown)},
        {key: "total_return", label: "Return", numeric: true, value: m("total_return"),
         cell: r => pct(r.metrics.total_return, 1), cls: r => tone(r.metrics.total_return)},
        {key: "excess", label: "vs SPY", numeric: true,
         value: r => r.metrics.cagr != null && r.benchmark.cagr != null ? r.metrics.cagr - r.benchmark.cagr : null,
         cell: r => r.benchmark.cagr == null ? "–" : spct(r.metrics.cagr - r.benchmark.cagr),
         cls: r => (r.benchmark.cagr == null ? "" : tone(r.metrics.cagr - r.benchmark.cagr))},
        {key: "fills", label: "Fills", numeric: true, value: m("fills"), cell: r => int(r.metrics.fills)},
        {key: "flags", label: "", cell: r => h("div", {class: "pills"},
            r.holdout ? h("span", {class: "flag", title: "Uses data from the holdout period"}, "holdout") : null,
            r.git_dirty ? h("span", {class: "flag quiet", title: "Code had uncommitted changes"}, "uncommitted") : null)},
    ];
    tableEl = sortableTable(cols, runs, {sortKey: "id", onRow: r => { location.hash = `#/runs/${r.id}`; }});
    return [head, h("p", {class: "sub"}, "Tick two to four runs to overlay them. Click a row for detail."),
            h("section", {class: "panel"}, tableEl)];
}

function figure(label, value, bench, cls) {
    return h("div", {class: "fig"}, h("div", {class: "label"}, label),
             h("div", {class: "value " + (cls || "")}, value),
             h("div", {class: "bench"}, bench ?? " "));
}

async function runPage(id) {
    const r = await api(`/api/runs/${id}`);
    const {cls, file} = strategyName(r.strategy);
    const M = r.metrics, B = r.benchmark;
    const BN = (B && B.name) || "SPY";
    const dates = r.equity.map(e => e[0]);
    const eq = r.equity.map(e => e[1]);
    const bench = r.equity.map(e => e[2]);
    const dd = xs => { let p = -Infinity; return xs.map(v => (v == null ? null : (p = Math.max(p, v), v / p - 1))); };

    const head = [
        h("a", {class: "back", href: "#/runs"}, "All runs"),
        h("div", {class: "head", style: "margin-top:6px"}, h("h1", {}, cls),
          h("span", {class: "count"}, `run ${r.id}`),
          r.holdout ? h("span", {class: "flag"}, "holdout") : null,
          r.git_dirty ? h("span", {class: "flag quiet"}, "uncommitted") : null,
          r.strategy_id ? h("a", {class: "mini-link", href: `#/strategies/${r.strategy_id}`}, `Edit strategy (ran v${r.version})`) : null),
        h("div", {style: "display:flex;gap:18px;flex-wrap:wrap;align-items:center;margin:-8px 0 18px;color:var(--dim)"},
          h("span", {}, r.symbols.join(" ")),
          h("span", {class: "pill", title: "Bar size the strategy traded on"}, h("i", {}, "bars "), r.config.timeframe || "1m"),
          h("span", {class: "num", style: "font-size:13px"}, `${day(r.start)} to ${day(r.end)}`),
          paramPills(r.params, ["symbol"])),
    ];

    const figs = h("div", {class: "figures"},
        figure("Total return", pct(M.total_return, 1), BN + " " + pct(B.total_return, 1), tone(M.total_return)),
        figure("CAGR", pct(M.cagr), BN + " " + pct(B.cagr), tone(M.cagr)),
        figure("Sharpe", num(M.sharpe), BN + " " + num(B.sharpe)),
        figure("Max drawdown", pct(M.max_drawdown), BN + " " + pct(B.max_drawdown)),
        figure("Exposure", pct(M.exposure, 1), `${int(M.bars)} bars`),
        figure("Fills", int(M.fills), `costs ${money(M.costs)}`));

    let log = false;
    const group = hoverGroup();
    const eqEl = h("div", {class: "chart"});
    const ddEl = h("div", {class: "chart"});
    const seg = h("div", {class: "seg", role: "group", "aria-label": "Equity scale"},
        ["Linear", "Log"].map(name => h("button", {"aria-pressed": String(name === "Linear"),
            onclick: ev => {
                log = name === "Log";
                seg.querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed", String(b === ev.target)));
                eqChart.redraw();
            }}, name)));
    const eqOpts = {
        dates, label: `Equity of the strategy and ${BN === "SPY" ? "SPY buy and hold" : BN}`, height: 340, fmt: money,
        tickFmt: v => (v === 0 ? "$0" : v >= 1e6 ? "$" + (v / 1e6).toFixed(1) + "M" : "$" + Math.round(v / 1e3) + "k"),
        endLabels: true, group, ref: r.config.cash,
        series: [{name: "Strategy", values: eq, color: "var(--s1)"},
                 {name: BN, values: bench, color: "var(--dim)", width: 1.5}],
    };
    Object.defineProperty(eqOpts, "log", {get: () => log});
    const eqPanel = h("section", {class: "panel"},
        h("h2", {}, "Equity", h("span", {class: "legend"},
            h("span", {style: "--c:var(--s1)"}, "Strategy"), h("span", {style: "--c:var(--dim)"}, BN === "SPY" ? "SPY buy and hold" : `${BN} (SPY/AGG, rebalanced monthly)`)),
          h("span", {class: "spacer"}), seg),
        h("div", {class: "body"}, eqEl));
    const ddPanel = h("section", {class: "panel"}, h("h2", {}, "Drawdown from peak"), h("div", {class: "body"}, ddEl));

    // Monthly grid
    const byYear = new Map();
    for (const [y, mo, v] of r.monthly) {
        if (!byYear.has(y)) byYear.set(y, Array(12).fill(null));
        byYear.get(y)[mo - 1] = v;
    }
    const yearEq = new Map();
    r.equity.forEach(([d, e]) => {
        const y = +d.slice(0, 4);
        if (!yearEq.has(y)) yearEq.set(y, [e, e]);
        yearEq.get(y)[1] = e;
    });
    const years = [...byYear.keys()];
    const yearRet = y => {
        const idx = years.indexOf(y);
        const start = idx > 0 ? yearEq.get(years[idx - 1])[1] : yearEq.get(y)[0];
        return yearEq.get(y)[1] / start - 1;
    };
    const allM = r.monthly.map(x => Math.abs(x[2] ?? 0)).sort((a, b) => a - b);
    const limit = allM[Math.floor(allM.length * 0.95)] || 0.05;
    const cell = (v, lim, title) => {
        const bg = diverging(v, lim);
        return h("div", {class: "cell", title, style: `background:${bg};color:${v == null ? "var(--faint)" : inkOn(bg)}`},
                 v == null ? "" : Math.abs(v) < 0.0005 ? "0.0" : (v * 100).toFixed(1).replace("-", MINUS));
    };
    const months = h("table", {class: "months"},
        h("thead", {}, h("tr", {}, h("th", {}, ""), MONTHS.map(mn => h("th", {}, mn)), h("th", {}, "Year"))),
        h("tbody", {}, years.map(y => h("tr", {}, h("td", {class: "yr"}, y),
            byYear.get(y).map((v, k) => h("td", {}, cell(v, limit, v == null ? "" : `${MONTHS[k]} ${y}: ${pct(v)}`))),
            h("td", {class: "total"}, cell(yearRet(y), limit * 3, `${y}: ${pct(yearRet(y))}`))))));
    const monthPanel = h("section", {class: "panel"},
        h("h2", {}, "Monthly returns, %", h("span", {class: "spacer"}),
          h("span", {class: "scale"}, MINUS + pct(limit, 0).replace(MINUS, ""),
            h("span", {class: "ramp", style: `background:linear-gradient(90deg, ${NEG}, ${MID}, ${POS})`}),
            "+" + pct(limit, 0))),
        h("div", {class: "body tablewrap"}, months));

    // Fills and details
    const fillsTable = sortableTable([
        {key: "ts", label: "Time (UTC)", value: f => f[0], cell: f => h("span", {class: "num", style: "font-size:12px"},
            f[0].replace("T", " ").slice(0, 16))},
        {key: "sym", label: "Symbol", cell: f => f[1]},
        {key: "qty", label: "Qty", numeric: true, value: f => f[2], cell: f => (f[2] > 0 ? "+" : "") + shares(f[2]).replace("-", MINUS),
         cls: f => tone(f[2])},
        {key: "px", label: "Price", numeric: true, value: f => f[3], cell: f => num(f[3], 2)},
        {key: "cost", label: "Cost", numeric: true, value: f => f[4], cell: f => num(f[4], 2)},
        {key: "pnl", label: "Realized", numeric: true, value: f => f[5], cell: f => (f[5] == null ? "" : num(f[5], 2)),
         cls: f => tone(f[5])},
    ], r.fills, {sortKey: "ts"});
    const fillsPanel = h("section", {class: "panel"},
        h("h2", {}, "Fills", h("span", {class: "count", style: "color:var(--dim);font-family:var(--mono);font-size:12px"},
            r.fill_count > r.fills.length ? `latest ${r.fills.length} of ${int(r.fill_count)}` : int(r.fill_count))),
        h("div", {style: "max-height:420px;overflow:auto"}, fillsTable));
    const c = r.config;
    const details = h("section", {class: "panel"}, h("h2", {}, "Run details"), h("div", {class: "body"},
        h("dl", {class: "kv"},
          h("dt", {}, "Strategy file"), h("dd", {}, file),
          h("dt", {}, "Bars"), h("dd", {}, c.timeframe || "1m"),
          h("dt", {}, "Starting cash"), h("dd", {}, money(c.cash)),
          h("dt", {}, "Slippage"), h("dd", {}, `${c.costs.slippage_bps} bps`),
          ...(c.engine === "portfolio" ? [
              h("dt", {}, "Decides"), h("dd", {}, `${c.rebalance}, 15:30 New York time, fills at 15:45`),
              h("dt", {}, "Shares"), h("dd", {}, c.fractional ? "fractional" : "whole only"),
              h("dt", {}, "Idle cash"), h("dd", {}, c.cash_yield ? "earns the T-bill rate" : "earns nothing"),
              h("dt", {}, "Option spread"), h("dd", {}, `${pct(c.costs.option_half_spread, 0)} of price each way, min $${c.costs.option_min_half_spread}`),
          ] : [
              h("dt", {}, "Commission"), h("dd", {}, `$${c.costs.commission_per_share}/share`),
              h("dt", {}, "Shorting"), h("dd", {}, c.allow_short ? "allowed" : "off"),
          ]),
          h("dt", {}, "SEC fee rate"), h("dd", {}, String(c.costs.sec_fee_rate)),
          h("dt", {}, "Sortino"), h("dd", {}, num(M.sortino) + `  (${BN} ` + num(B.sortino) + ")"),
          h("dt", {}, "Volatility"), h("dd", {}, pct(M.ann_vol) + `  (${BN} ` + pct(B.ann_vol) + ")"),
          h("dt", {}, "Longest drawdown"), h("dd", {}, `${int(M.max_drawdown_days)} days`),
          h("dt", {}, "Win rate"), h("dd", {}, pct(M.win_rate, 1) + " of closing fills"),
          h("dt", {}, "Turnover"), h("dd", {}, num(M.turnover, 1) + "× equity a year"),
          h("dt", {}, "Engine time"), h("dd", {}, num(r.duration_s, 2) + " s"),
          h("dt", {}, "Commit"), h("dd", {}, (r.git_commit || "–").slice(0, 10) + (r.git_dirty ? " + uncommitted changes" : "")),
          h("dt", {}, "Strategy SHA-256"), h("dd", {}, r.strategy_sha256.slice(0, 16)),
          h("dt", {}, "Created"), h("dd", {}, r.created_at.replace("T", " ").slice(0, 16) + " UTC"))));

    const tf = r.config.timeframe || "1m";
    const pcEl = h("div", {class: "pc"});
    const pricePanel = h("section", {class: "panel"}, h("h2", {}, "Price chart",
        h("span", {class: "legend"}, h("span", {style: "--c:#3987e5"}, "▲ buy"), h("span", {style: "--c:#e8833a"}, "▼ sell"))),
        h("div", {class: "body"}, pcEl));
    onMount(async () => {
        const {priceChart, presetsFor} = await import("/static/pricechart.js");
        const last = new Date(new Date(r.end) - 86400000).toISOString().slice(0, 10);
        // Open on the strategy's own bars so its indicators and trades line up exactly; minute
        // strategies open on 15m, which is easier to read and still close.
        const pc = priceChart(pcEl, {
            symbol: r.symbols[0], symbols: r.symbols, tf: tf === "1m" ? "15m" : tf, end: last,
            minDate: r.start.slice(0, 10), exactTf: tf, runId: r.id, indicators: presetsFor(r.params, tf),
            storeKey: `run.${r.id}`, visible: 160,
        }, {h, api, num, int, pct});
        cleanups.push(pc.destroy);
    });

    const nodes = [...head, figs, pricePanel, eqPanel, ddPanel, monthPanel, h("div", {class: "grid2"}, fillsPanel, details)];
    const eqChart = {redraw() {}};
    onMount(() => {
        const ec = lineChart(eqEl, eqOpts);
        eqChart.redraw = ec.redraw;
        const dc = lineChart(ddEl, {dates, label: "Drawdown from peak", height: 170, zeroTop: true, group,
            fmt: v => pct(v), tickFmt: v => pct(v, 0), endLabels: true,
            series: [{name: "Strategy", values: dd(eq), color: "var(--s1)"},
                     {name: BN, values: dd(bench), color: "var(--dim)", width: 1.5}]});
        refreshers.push(ec.redraw, dc.redraw);
    });
    return nodes;
}

async function comparePage(ids) {
    const runs = await Promise.all(ids.map(id => api(`/api/runs/${id}`)));
    const allDates = [...new Set(runs.flatMap(r => r.equity.map(e => e[0])))].sort();
    const series = runs.map((r, k) => {
        const map = new Map(r.equity.map(e => [e[0], e[1]]));
        const first = r.equity[0][1];
        let last = null;
        return {name: `Run ${r.id}`, color: SERIES[k], values: allDates.map(d => {
            if (map.has(d)) { last = map.get(d) / first * 100; return last; }
            return d < r.equity[0][0] || d > r.equity[r.equity.length - 1][0] ? null : last;
        })};
    });
    const el = h("div", {class: "chart"});
    const keys = ["total_return", "cagr", "sharpe", "sortino", "max_drawdown", "ann_vol", "exposure",
                  "fills", "win_rate", "turnover", "costs"];
    const best = k => {
        const meta = METRICS[k];
        if (!meta.better) return null;
        const vals = runs.map(r => r.metrics[k]).filter(v => v != null);
        return meta.better === "high" ? Math.max(...vals) : Math.min(...vals);
    };
    const table = h("table", {},
        h("thead", {}, h("tr", {}, h("th", {}, "Metric"), runs.map((r, k) => h("th", {class: "n"},
            h("span", {class: "legend"}, h("span", {style: `--c:${SERIES[k]}`}, `Run ${r.id}`)))))),
        h("tbody", {},
          h("tr", {}, h("td", {}, "Strategy"), runs.map(r => h("td", {class: "n", style: "font-family:var(--sans)"}, strategyName(r.strategy).cls))),
          h("tr", {}, h("td", {}, "Params"), runs.map(r => h("td", {class: "n"}, paramPills(r.params, ["symbol"])))),
          h("tr", {}, h("td", {}, "Window"), runs.map(r => h("td", {class: "n"}, `${day(r.start)} to ${day(r.end)}`))),
          keys.map(k => {
              const b = best(k);
              return h("tr", {}, h("td", {}, METRICS[k].label), runs.map(r => {
                  const v = r.metrics[k];
                  const top = b != null && v === b && runs.length > 1;
                  return h("td", {class: "n", style: top ? "color:var(--signal)" : "",
                                  title: top ? "Best of the compared runs" : null},
                           METRICS[k].fmt(v) + (top ? " ●" : ""));
              }));
          })));
    onMount(() => {
        const c = lineChart(el, {dates: allDates, series, height: 380, fmt: v => num(v, 1),
                                 tickFmt: v => num(v, 0), endLabels: true, ref: 100,
                                 label: "Equity of each run, rebased to 100 at its first day"});
        refreshers.push(c.redraw);
    });
    return [
        h("a", {class: "back", href: "#/runs"}, "All runs"),
        h("div", {class: "head", style: "margin-top:6px"}, h("h1", {}, `Comparing ${runs.length} runs`)),
        h("section", {class: "panel"}, h("h2", {}, "Equity, rebased to 100",
            h("span", {class: "legend"}, series.map(sr => h("span", {style: `--c:${sr.color}`}, sr.name)))),
          h("div", {class: "body"}, el)),
        h("section", {class: "panel"}, h("h2", {}, "Metrics", h("span", {class: "spacer"}),
            h("span", {style: "font-size:13px;color:var(--dim);font-weight:400"}, "● best of these runs")),
          h("div", {class: "tablewrap"}, table)),
    ];
}

async function chartPage(q) {
    const cfg = await api("/api/lab");
    const today = new Date().toISOString().slice(0, 10);
    const pcEl = h("div", {class: "pc"});
    onMount(async () => {
        const {priceChart} = await import("/static/pricechart.js");
        const sym = (q.get("symbol") || "SPY").toUpperCase();
        const pc = priceChart(pcEl, {
            symbol: cfg.symbols.includes(sym) ? sym : cfg.symbols[0], symbols: cfg.symbols, tf: "1h",
            end: today, minDate: cfg.history_start, visible: 400,
            indicators: [{type: "sma", len: 20, unit: "c"}, {type: "bb", len: 20, unit: "c", k: 2}],
        }, {h, api, num, int, pct});
        cleanups.push(pc.destroy);
    });
    return [h("div", {class: "head"}, h("h1", {}, "Chart")),
            h("section", {class: "panel"}, h("div", {class: "body"}, pcEl))];
}

async function sweepsPage() {
    const sweeps = await api("/api/sweeps");
    const head = h("div", {class: "head"}, h("h1", {}, "Sweeps"), h("span", {class: "count"}, `${sweeps.length}`));
    if (!sweeps.length) {
        return [head, h("section", {class: "panel"}, empty("No sweeps yet. Run one from the terminal:",
            "uv run btest sweep strategies/trend/ma_cross.py SPY --start 2016-01-01 -g fast=5,10,30 -g slow=60:2340:60"))];
    }
    const table = sortableTable([
        {key: "id", label: "Sweep", numeric: true, value: x => x.id, cell: x => x.id},
        {key: "strategy", label: "Strategy", value: x => x.strategy, tdClass: "strategy",
         cell: x => [strategyName(x.strategy).cls, h("small", {}, strategyName(x.strategy).file)]},
        {key: "symbol", label: "Symbol", cell: x => x.symbol},
        {key: "window", label: "Window", value: x => x.start,
         cell: x => h("span", {class: "num", style: "font-size:13px"}, `${day(x.start)} to ${day(x.end)}`)},
        {key: "grid", label: "Grid", cell: x => h("div", {class: "pills"}, Object.entries(x.grid).map(([k, v]) =>
            h("span", {class: "pill"}, h("i", {}, k + " "), v.length > 4 ? `${v[0]}…${v[v.length - 1]} (${v.length})` : v.join(", "))))},
        {key: "combos", label: "Runs", numeric: true, value: x => x.combos - x.skipped, cell: x => int(x.combos - x.skipped)},
        {key: "best", label: "Best Sharpe", numeric: true, value: x => x.best_sharpe, cell: x => num(x.best_sharpe)},
        {key: "dur", label: "Time", numeric: true, value: x => x.duration_s, cell: x => num(x.duration_s, 1) + " s"},
    ], sweeps, {sortKey: "id", onRow: x => { location.hash = `#/sweeps/${x.id}`; }});
    return [head, h("section", {class: "panel"}, table)];
}

async function sweepPage(id) {
    const sw = await api(`/api/sweeps/${id}`);
    const params = Object.keys(sw.grid);
    const varying = params.filter(p => sw.grid[p].length > 1);
    const metricKeys = ["sharpe", "cagr", "total_return", "max_drawdown", "sortino", "ann_vol", "fills", "exposure"];
    const st = {
        metric: "sharpe",
        x: varying.length > 1 ? varying[varying.length - 1] : varying[0] || params[0],
        y: varying.length > 1 ? varying[0] : null,
        fixed: {},
    };
    const key = p => JSON.stringify(p);
    const better = k => (METRICS[k].better === "low" ? -1 : 1);

    const heatEl = h("div", {class: "chart"});
    const noteEl = h("div");
    const scaleEl = h("span", {class: "scale"});
    const fixedEl = h("div", {class: "controls"});
    const sel = (label, options, value, on) => h("label", {}, label, h("select", {onchange: ev => on(ev.target.value)},
        options.map(([v, t]) => h("option", {value: v, selected: v === value}, t))));

    function rowsFor() {
        return sw.results.filter(r => params.every(p => p === st.x || p === st.y
            || key(r.params[p]) === key(st.fixed[p] ?? sw.grid[p][0])));
    }

    function renderFixed() {
        fixedEl.replaceChildren(...params.filter(p => p !== st.x && p !== st.y && sw.grid[p].length > 1).map(p =>
            sel(`${p} fixed at`, sw.grid[p].map(v => [key(v), String(v)]), key(st.fixed[p] ?? sw.grid[p][0]),
                v => { st.fixed[p] = JSON.parse(v); drawHeat(); })));
    }

    function drawHeat() {
        const rows = rowsFor();
        const xs = sw.grid[st.x], ys = st.y ? sw.grid[st.y] : [null];
        const at = new Map(rows.map(r => [key(r.params[st.x]) + "|" + (st.y ? key(r.params[st.y]) : ""), r]));
        const get = (xv, yv) => at.get(key(xv) + "|" + (st.y ? key(yv) : ""));
        const vals = rows.map(r => r.metrics[st.metric]).filter(v => v != null).sort((a, b) => a - b);
        const dir = better(st.metric);
        // Clip the worst 5% so a few terrible settings don't wash out the region worth reading.
        const q = f => vals[Math.min(vals.length - 1, Math.max(0, Math.round(f * (vals.length - 1))))];
        const lo = dir > 0 ? q(0.05) : vals[0], hi = dir > 0 ? vals[vals.length - 1] : q(0.95);
        const clipped = dir > 0 ? vals[0] < lo : vals[vals.length - 1] > hi;
        const norm = v => (hi === lo ? 1 : Math.max(0, Math.min(1, (v - lo) / (hi - lo))));
        const bestRow = rows.reduce((b, r) => (r.metrics[st.metric] != null && (!b || dir * r.metrics[st.metric] > dir * b.metrics[st.metric]) ? r : b), null);

        heatEl.replaceChildren();
        const W = Math.max(280, heatEl.clientWidth);
        const m = {l: st.y ? 64 : 16, r: 8, t: 8, b: 40};
        const cw = (W - m.l - m.r) / xs.length;
        const ch = st.y ? Math.max(22, Math.min(44, 300 / ys.length)) : 48;
        const H = m.t + ch * ys.length + m.b;
        const svg = s("svg", {viewBox: `0 0 ${W} ${H}`, height: H, role: "img",
                              "aria-label": `${METRICS[st.metric].label} for each ${st.x}${st.y ? " and " + st.y : ""}`});
        const showText = cw >= 38 && ch >= 20;
        ys.forEach((yv, yi) => {
            if (st.y) {
                const t = s("text", {x: m.l - 8, y: m.t + ch * yi + ch / 2 + 4, "text-anchor": "end",
                                     fill: "var(--dim)", "font-size": 11, "font-family": "var(--mono)"}, svg);
                t.textContent = yv;
            }
            xs.forEach((xv, xi) => {
                const r = get(xv, yv);
                const v = r ? r.metrics[st.metric] : null;
                const fill = v == null ? "transparent" : ramp(SEQ, dir > 0 ? norm(v) : 1 - norm(v));
                const rect = s("rect", {x: m.l + cw * xi + 1.5, y: m.t + ch * yi + 1.5, width: Math.max(1, cw - 3),
                                        height: ch - 3, rx: 2, fill,
                                        stroke: v == null ? "var(--rule-2)" : "none",
                                        "stroke-dasharray": v == null ? "2 2" : "none"}, svg);
                if (r && showText) {
                    const t = s("text", {x: m.l + cw * xi + cw / 2, y: m.t + ch * yi + ch / 2 + 4, "text-anchor": "middle",
                                         fill: inkOn(fill.startsWith("#") ? fill : "#141a24"), "font-size": 10.5,
                                         "font-family": "var(--mono)", "pointer-events": "none"}, svg);
                    t.textContent = METRICS[st.metric].fmt(v).replace("%", "");
                }
                rect.addEventListener("pointermove", ev => {
                    if (!r) { showTip(ev.clientX, ev.clientY, "Skipped", [["Not a valid combination", ""]]); return; }
                    showTip(ev.clientX, ev.clientY, params.map(p => `${p}=${r.params[p]}`).join("  "),
                            ["sharpe", "cagr", "max_drawdown", "total_return", "fills"].map(k => [METRICS[k].label, METRICS[k].fmt(r.metrics[k])]));
                });
                rect.addEventListener("pointerleave", hideTip);
                if (r && r === bestRow) {
                    s("rect", {x: m.l + cw * xi + 0.5, y: m.t + ch * yi + 0.5, width: cw - 1, height: ch - 1, rx: 3,
                               fill: "none", stroke: "var(--signal)", "stroke-width": 2, "pointer-events": "none"}, svg);
                }
            });
        });
        const every = Math.ceil(46 / cw);
        xs.forEach((xv, xi) => {
            if (xi % every && xi !== xs.length - 1) return;
            const t = s("text", {x: m.l + cw * xi + cw / 2, y: m.t + ch * ys.length + 16, "text-anchor": "middle",
                                 fill: "var(--dim)", "font-size": 11, "font-family": "var(--mono)"}, svg);
            t.textContent = xv;
        });
        const xl = s("text", {x: m.l + (W - m.l - m.r) / 2, y: H - 4, "text-anchor": "middle", fill: "var(--faint)", "font-size": 12}, svg);
        xl.textContent = st.x;
        if (st.y) {
            const yl = s("text", {x: 12, y: m.t + ch * ys.length / 2, "text-anchor": "middle", fill: "var(--faint)",
                                  "font-size": 12, transform: `rotate(-90 12 ${m.t + ch * ys.length / 2})`}, svg);
            yl.textContent = st.y;
        }
        heatEl.appendChild(svg);

        const fmt = METRICS[st.metric].fmt;
        scaleEl.replaceChildren((clipped ? "\u2264 " : "") + (dir > 0 ? fmt(lo) : fmt(hi)),
            h("span", {class: "ramp", style: `background:linear-gradient(90deg, ${SEQ.join(",")})`}),
            dir > 0 ? fmt(hi) : fmt(lo), h("span", {style: "color:var(--faint)"}, "brighter is better, dashed was skipped"));

        noteEl.replaceChildren();
        if (bestRow) {
            const edges = [st.x, st.y].filter(Boolean).filter(p => {
                const g = sw.grid[p], v = key(bestRow.params[p]);
                return g.length > 2 && (v === key(g[0]) || v === key(g[g.length - 1]));
            });
            const xi = xs.findIndex(v => key(v) === key(bestRow.params[st.x]));
            const yi = st.y ? ys.findIndex(v => key(v) === key(bestRow.params[st.y])) : 0;
            const nb = [];
            for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
                if (!dx && !dy) continue;
                const r = xs[xi + dx] !== undefined && ys[yi + dy] !== undefined ? get(xs[xi + dx], ys[yi + dy]) : null;
                if (r && r.metrics[st.metric] != null) nb.push(r.metrics[st.metric]);
            }
            const nbMean = nb.length ? nb.reduce((a, b) => a + b, 0) / nb.length : null;
            const bestTxt = `Best ${METRICS[st.metric].label.toLowerCase()} ${fmt(bestRow.metrics[st.metric])} at `
                + [st.x, st.y].filter(Boolean).map(p => `${p}=${bestRow.params[p]}`).join(", ") + ".";
            const nbTxt = nbMean == null ? "" : ` Its ${nb.length} neighbours average ${fmt(nbMean)}.`;
            const lines = [bestTxt + nbTxt];
            if (edges.length) {
                lines.push(` It sits on the edge of the grid for ${edges.join(" and ")}, so a better setting may lie outside the range tried. Extend the grid before trusting it.`);
            }
            noteEl.replaceChildren(h("div", {class: edges.length ? "note" : "", style: edges.length ? "" : "color:var(--dim);margin-bottom:12px"}, lines.join("")));
        }
    }

    const axisOpts = params.map(p => [p, `${p} (${sw.grid[p].length})`]);
    const controls = h("div", {class: "controls", style: "margin-bottom:14px"},
        sel("Metric", metricKeys.map(k => [k, METRICS[k].label]), st.metric, v => { st.metric = v; drawHeat(); renderTop(); }),
        sel("Columns", axisOpts, st.x, v => { if (v === st.y) st.y = st.x; st.x = v; renderFixed(); drawHeat(); }),
        params.length > 1 ? sel("Rows", axisOpts, st.y, v => { if (v === st.x) st.x = st.y; st.y = v; renderFixed(); drawHeat(); }) : null,
        fixedEl);

    const topEl = h("div");
    function renderTop() {
        const dir = better(st.metric);
        const sorted = [...sw.results].filter(r => r.metrics[st.metric] != null)
            .sort((a, b) => dir * (b.metrics[st.metric] - a.metrics[st.metric])).slice(0, 20);
        topEl.replaceChildren(sortableTable([
            ...params.map(p => ({key: p, label: p, numeric: true, value: r => r.params[p], cell: r => String(r.params[p])})),
            ...["sharpe", "cagr", "max_drawdown", "total_return", "sortino", "fills", "exposure"].map(k => ({
                key: k, label: METRICS[k].label, numeric: true, value: r => r.metrics[k], cell: r => METRICS[k].fmt(r.metrics[k]),
                cls: r => (k === "cagr" || k === "total_return" ? tone(r.metrics[k]) : ""),
            })),
        ], sorted, {}));
    }

    const {cls, file} = strategyName(sw.strategy);
    const fixedParams = Object.entries(sw.fixed || {});
    renderFixed();
    renderTop();
    onMount(() => { drawHeat(); refreshers.push(drawHeat); });
    return [
        h("a", {class: "back", href: "#/sweeps"}, "All sweeps"),
        h("div", {class: "head", style: "margin-top:6px"}, h("h1", {}, cls), h("span", {class: "count"}, `sweep ${sw.id}`)),
        h("div", {style: "display:flex;gap:18px;flex-wrap:wrap;align-items:center;margin:-8px 0 18px;color:var(--dim)"},
          h("span", {}, sw.symbol),
          h("span", {class: "pill"}, h("i", {}, "bars "), sw.config.timeframe || "1m"),
          h("span", {class: "num", style: "font-size:13px"}, `${day(sw.start)} to ${day(sw.end)}`),
          h("span", {}, `${int(sw.combos - sw.skipped)} runs in ${num(sw.duration_s, 1)} s, ${sw.skipped} skipped`),
          fixedParams.length ? paramPills(sw.fixed) : null,
          h("span", {}, `holdout from ${sw.holdout_start}, untouched`)),
        h("section", {class: "panel heat"}, h("h2", {}, "Parameter map", h("span", {class: "spacer"}), scaleEl),
          h("div", {class: "body"}, controls, noteEl, heatEl)),
        h("section", {class: "panel"}, h("h2", {}, "Top 20 settings"), topEl),
    ];
}

async function dataPage() {
    const d = await api("/api/data");
    const table = sortableTable([
        {key: "symbol", label: "Symbol", value: x => x.symbol, cell: x => h("b", {}, x.symbol)},
        {key: "first", label: "First bar (UTC)", value: x => x.first, cell: x => h("span", {class: "num", style: "font-size:13px"}, (x.first || "–").replace("T", " ").slice(0, 16))},
        {key: "last", label: "Last bar (UTC)", value: x => x.last, cell: x => h("span", {class: "num", style: "font-size:13px"}, (x.last || "–").replace("T", " ").slice(0, 16))},
        {key: "bars", label: "Minute bars", numeric: true, value: x => x.bars, cell: x => int(x.bars)},
        {key: "regular", label: "Regular session", numeric: true, value: x => x.regular_bars, cell: x => int(x.regular_bars)},
        {key: "splits", label: "Splits", cell: x => x.splits.length ? h("div", {class: "pills"}, x.splits.map(sp =>
            h("span", {class: "pill"}, `${sp.ex_date} ${+sp.ratio >= 1 ? sp.ratio + ":1" : "1:" + 1 / sp.ratio}`))) : h("span", {style: "color:var(--faint)"}, "none")},
        {key: "divs", label: "Dividends", numeric: true, value: x => x.dividends, cell: x => int(x.dividends)},
        {key: "lastdiv", label: "Latest ex-date", cell: x => h("span", {class: "num", style: "font-size:13px"}, x.last_dividend || "–")},
    ], d.symbols, {sortKey: "symbol", sortDir: 1});
    return [
        h("div", {class: "head"}, h("h1", {}, "Data")),
        h("p", {class: "sub"}, "Raw minute bars from Alpaca (SIP feed), stored locally as Parquet. Backtests read only this copy."),
        h("section", {class: "panel"}, table),
        h("section", {class: "panel"}, h("h2", {}, "Settings"), h("div", {class: "body"}, h("dl", {class: "kv"},
            h("dt", {}, "History starts"), h("dd", {}, d.history_start),
            h("dt", {}, "Holdout starts"), h("dd", {}, `${d.holdout_start} (sweeps stop before this)`),
            h("dt", {}, "Risk-free rate"), h("dd", {}, d.risk_free ? `${d.risk_free.value.toFixed(2)}% 3-month T-bill on ${d.risk_free.date}` : "not loaded"),
            h("dt", {}, "Update data"), h("dd", {}, "uv run btest ingest")))),
    ];
}

// ---------- router ----------

let labModule = null;
let routeToken = 0;

async function route() {
    const token = ++routeToken;
    hideTip();
    refreshers = [];
    mounts = [];
    cleanups.forEach(f => f());
    cleanups = [];
    const hash = location.hash || "#/strategies";
    const [path, query] = hash.slice(2).split("?");
    const parts = path.split("/");
    const tab = parts[0] === "compare" ? "runs" : parts[0];
    const inLab = parts[0] === "strategies";
    document.body.classList.toggle("full", inLab);
    if (!inLab && labModule) labModule.leaveLab();
    document.querySelectorAll(".tabs a").forEach(a => {
        if (a.dataset.tab === tab) a.setAttribute("aria-current", "page");
        else a.removeAttribute("aria-current");
    });
    let nodes;
    try {
        if (inLab) {
            labModule = labModule || await import("/static/lab.js");
            nodes = await labModule.labPage(parts[1] ? +parts[1] : null, {
                h, api, write, pct, num, int, tone, money, onMount, lineChart, addCleanup: f => cleanups.push(f)});
        } else if (parts[0] === "runs" && parts[1]) nodes = await runPage(+parts[1]);
        else if (parts[0] === "chart") nodes = await chartPage(new URLSearchParams(query));
        else if (parts[0] === "compare") {
            const ids = new URLSearchParams(query).get("ids")?.split(",").map(Number).filter(Boolean) || [];
            nodes = ids.length ? await comparePage(ids) : [empty("Pick runs to compare on the Runs page.")];
        } else if (parts[0] === "sweeps" && parts[1]) nodes = await sweepPage(+parts[1]);
        else if (parts[0] === "sweeps") nodes = await sweepsPage();
        else if (parts[0] === "data") nodes = await dataPage();
        else nodes = await runsPage();
    } catch (err) {
        const hint = err.status === 404 ? null
            : h("div", {style: "margin-top:8px;color:var(--dim)"}, "Check that Postgres is running and `uv run btest migrate` has been applied.");
        nodes = [h("section", {class: "panel"}, h("div", {class: "empty error"}, err.message, hint))];
    }
    if (token !== routeToken) return;
    view.replaceChildren(...nodes);
    mounts.forEach(f => f());
    document.title = (view.querySelector("h1")?.textContent || "btest") + " | btest";
    if (!inLab) window.scrollTo(0, 0);
}

async function status() {
    try {
        const d = await api("/api/data");
        const last = d.symbols.map(x => x.last).filter(Boolean).sort().pop();
        document.getElementById("status").replaceChildren(
            h("span", {}, "bars through ", h("b", {}, last ? last.replace("T", " ").slice(0, 16) + "Z" : "–")),
            h("span", {}, "holdout from ", h("b", {}, d.holdout_start)));
    } catch { /* the page itself reports connection problems */ }
}

window.addEventListener("hashchange", route);
route();
status();
