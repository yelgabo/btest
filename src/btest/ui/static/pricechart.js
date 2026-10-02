// Candlestick chart with indicator overlays and a run's fills, on TradingView's
// lightweight-charts (loaded as a global from the CDN in index.html).

const LWC = () => window.LightweightCharts;
const TF_MIN = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "1D": 390};
const UP = "#3ccf7a", DOWN = "#f06a6a", BUY = "#3987e5", SELL = "#e8833a";
const LINE_COLORS = ["#3987e5", "#c98500", "#199e70", "#d55181"];
const BAND = "#9085e9";

const DAY_MS = 86400000;
const CHUNK = 3000;
const EDGE = 150;
const MAX_LOADED = 400000;
const iso = d => d.toISOString().slice(0, 10);
const addDays = (day, n) => iso(new Date(Date.parse(day) + n * DAY_MS));
const today = () => iso(new Date());
const EMPTY = () => ({t: [], o: [], h: [], l: [], c: [], v: [], f: []});

const etDate = new Intl.DateTimeFormat("en-US", {timeZone: "America/New_York", month: "short", day: "numeric", year: "numeric"});
const etTime = new Intl.DateTimeFormat("en-US", {timeZone: "America/New_York", hour: "2-digit", minute: "2-digit", hour12: false});
const etMonth = new Intl.DateTimeFormat("en-US", {timeZone: "America/New_York", month: "short"});
const etYear = new Intl.DateTimeFormat("en-US", {timeZone: "America/New_York", year: "numeric"});
const etDay = new Intl.DateTimeFormat("en-US", {timeZone: "America/New_York", day: "numeric", month: "short"});

function sma(c, n) {
    const out = new Array(c.length).fill(null);
    let sum = 0;
    for (let i = 0; i < c.length; i++) {
        sum += c[i];
        if (i >= n) sum -= c[i - n];
        if (i >= n - 1) out[i] = sum / n;
    }
    return out;
}

function ema(c, n) {
    const out = new Array(c.length).fill(null);
    const a = 2 / (n + 1);
    let v = null;
    for (let i = 0; i < c.length; i++) {
        if (i === n - 1) v = c.slice(0, n).reduce((x, y) => x + y, 0) / n;
        else if (i >= n) v = a * c[i] + (1 - a) * v;
        if (i >= n - 1) out[i] = v;
    }
    return out;
}

// Population standard deviation, the same definition the z-score strategy uses. Running sums
// over prices centred on the first close keep it O(n) without losing precision.
function bollinger(c, n, k) {
    const len = c.length;
    const mid = new Array(len).fill(null), up = new Array(len).fill(null), lo = new Array(len).fill(null);
    if (!len) return {mid, up, lo};
    const base = c[0];
    let s1 = 0, s2 = 0;
    for (let i = 0; i < len; i++) {
        const d = c[i] - base;
        s1 += d; s2 += d * d;
        if (i >= n) { const o = c[i - n] - base; s1 -= o; s2 -= o * o; }
        if (i >= n - 1) {
            const m = s1 / n;
            const sd = Math.sqrt(Math.max(s2 / n - m * m, 0));
            mid[i] = base + m;
            up[i] = mid[i] + k * sd;
            lo[i] = mid[i] - k * sd;
        }
    }
    return {mid, up, lo};
}

const store = {
    get(key, fallback) { try { const v = localStorage.getItem("btest.chart." + key); return v ? JSON.parse(v) : fallback; } catch { return fallback; } },
    set(key, value) { try { localStorage.setItem("btest.chart." + key, JSON.stringify(value)); } catch { /* private mode */ } },
};

// Indicators the strategy itself uses, read from its params. Params count bars of the
// strategy's timeframe; they are stored in minutes so they stay true to the strategy whatever
// the chart's candle size.
export function presetsFor(params, timeframe = "1m") {
    const p = params || {};
    const m = TF_MIN[timeframe] || 1;
    if (typeof p.fast === "number" && typeof p.slow === "number") {
        return [{type: "sma", len: p.fast * m, unit: "min"}, {type: "sma", len: p.slow * m, unit: "min"}];
    }
    if (typeof p.window === "number" && typeof p.entry_z === "number") {
        return [{type: "bb", len: p.window * m, unit: "min", k: p.entry_z}];
    }
    if (typeof p.length === "number") return [{type: "sma", len: p.length * m, unit: "min"}];
    return [{type: "sma", len: 20, unit: "c"}];
}

export function priceChart(root, opts, ui) {
    const {h, api, num, int, pct} = ui;
    const key = opts.storeKey || "free";
    const saved = store.get(key, {});
    const st = {
        symbol: saved.symbol && opts.symbols.includes(saved.symbol) ? saved.symbol : opts.symbol,
        tf: saved.tf || opts.tf,
        end: saved.end || opts.end,
        indicators: (!opts.freshIndicators && saved.indicators) || opts.indicators,
    };
    const persist = () => store.set(key, st);
    const exactTf = opts.exactTf || "1m";
    let data = EMPTY(), fills = [], chart = null, candleSeries = null, volSeries = null, markersApi = null;
    let lineSeries = [];
    let loadToken = 0;

    const legendEl = h("div", {class: "pc-legend"});
    const noteEl = h("div", {class: "pc-note"});
    const chartEl = h("div", {class: "pc-chart"});
    const indEl = h("div", {class: "pc-inds"});
    const tfSeg = h("div", {class: "seg", role: "group", "aria-label": "Timeframe"});

    function periodCandles(ind) {
        if (ind.unit !== "min") return Math.max(1, Math.round(ind.len));
        return Math.max(2, Math.round(ind.len / TF_MIN[st.tf]));
    }
    function label(ind) {
        if (ind.type === "custom") return ind.name.split("/").pop();
        return {sma: "SMA", ema: "EMA", bb: "BB"}[ind.type];
    }
    const OWN_COLORS = ["#c98500", "#3987e5", "#199e70", "#d55181"];
    let customList = null;
    // Lines of each custom indicator, aligned to data.t; rebuilt on every reset.
    let customData = new Map();
    const customKey = ind => JSON.stringify([ind.id, ind.params]);

    function renderTf() {
        tfSeg.replaceChildren(...Object.keys(TF_MIN).map(tf => h("button", {"aria-pressed": String(tf === st.tf), onclick: () => {
            // Keep looking at the same moment when the candle size changes.
            const r = chart && chart.timeScale().getVisibleLogicalRange();
            if (ready && r && data.t.length) {
                const i = Math.max(0, Math.min(data.t.length - 1, Math.round(r.to)));
                st.end = iso(new Date(data.t[i] * 1000));
                goTo.value = st.end;
            }
            st.tf = tf; persist(); renderTf(); renderInds(); reset();
        }}, tf)));
    }

    function customChip(ind, i) {
        const inputs = Object.entries(ind.defaults || {}).map(([k, dv]) => {
            const v = k in ind.params ? ind.params[k] : dv;
            return [h("small", {}, k), h("input", {type: typeof dv === "number" ? "number" : "text", value: v,
                step: typeof dv === "number" && !Number.isInteger(dv) ? "any" : 1, "aria-label": `${label(ind)} ${k}`,
                onchange: ev => {
                    const raw = ev.target.value;
                    ind.params[k] = typeof dv === "number" ? +raw : raw;
                    persist(); reset();
                }})];
        });
        return h("span", {class: "pc-chip", style: `--c:${ind.pane === "own" ? OWN_COLORS[0] : LINE_COLORS[i % LINE_COLORS.length]}`,
                          title: `Custom indicator ${ind.name}${ind.pane === "own" ? ", in its own pane" : ""}`},
            h("b", {}, label(ind)), ...inputs.flat(),
            opts.lockCustom === ind.id ? null : h("button", {class: "icon", "aria-label": `Remove ${label(ind)}`, onclick: () => {
                st.indicators.splice(i, 1); persist(); renderInds(); drawIndicators();
            }}, "×"));
    }

    async function addCustom(id) {
        const d = await api(`/api/strategies/${id}`);
        st.indicators.push({type: "custom", id: d.id, name: d.name, params: {}, defaults: d.params,
                            pane: d.pane, levels: d.levels});
        persist(); renderInds(); reset();
    }

    // The preview in the editor calls this after each save so the chip and panes follow the code.
    function updateCustom(id, d) {
        for (const ind of st.indicators) {
            if (ind.type === "custom" && ind.id === id) {
                ind.name = d.name; ind.defaults = d.params; ind.pane = d.pane; ind.levels = d.levels;
                for (const k of Object.keys(ind.params)) if (!(k in d.params)) delete ind.params[k];
            }
        }
        persist(); renderInds(); reset();
    }

    function renderInds() {
        indEl.replaceChildren(...st.indicators.map((ind, i) => {
            if (ind.type === "custom") return customChip(ind, i);
            const color = ind.type === "bb" ? BAND : LINE_COLORS[i % LINE_COLORS.length];
            // Strategy presets are kept in minutes but shown in the strategy's own bars.
            const per = ind.unit === "min" ? TF_MIN[exactTf] : 1;
            const lenInput = h("input", {type: "number", min: 1, step: 1, value: ind.len / per, "aria-label": `${label(ind)} length`,
                onchange: ev => { const v = +ev.target.value; if (v >= 1) { ind.len = v * per; persist(); renderInds(); drawIndicators(); } }});
            const approx = ind.unit === "min" && st.tf !== exactTf;
            return h("span", {class: "pc-chip", style: `--c:${color}`, title: ind.unit === "min"
                ? `${ind.len} minutes = ${periodCandles(ind)} ${st.tf} candles.${approx ? ` Switch to ${exactTf} to match the strategy exactly.` : ""}` : null},
                h("b", {}, label(ind)), lenInput,
                h("small", {}, ind.unit !== "min" ? "bars" : exactTf === "1m" ? "min" : `${exactTf} bars`),
                ind.type === "bb" ? [h("input", {type: "number", min: 0.1, step: 0.1, value: ind.k, "aria-label": "Band width in standard deviations",
                    onchange: ev => { const v = +ev.target.value; if (v > 0) { ind.k = v; persist(); drawIndicators(); } }}), h("small", {}, "σ")] : null,
                h("button", {class: "icon", "aria-label": `Remove ${label(ind)}`, onclick: () => {
                    st.indicators.splice(i, 1); persist(); renderInds(); drawIndicators();
                }}, "×"));
        }), h("select", {"aria-label": "Add indicator", onchange: ev => {
            const type = ev.target.value;
            ev.target.value = "";
            if (!type) return;
            if (type.startsWith("custom:")) return addCustom(+type.slice(7));
            st.indicators.push(type === "bb" ? {type, len: 20, unit: "c", k: 2} : {type, len: type === "ema" ? 9 : 20, unit: "c"});
            persist(); renderInds(); drawIndicators();
        }}, h("option", {value: ""}, "Add indicator"), h("option", {value: "sma"}, "SMA, simple moving average"),
            h("option", {value: "ema"}, "EMA, exponential moving average"), h("option", {value: "bb"}, "Bollinger bands"),
            customList && customList.length ? h("optgroup", {label: "Your indicators"},
                customList.map(c => h("option", {value: `custom:${c.id}`}, c.name))) : null));
    }

    const goTo = h("input", {type: "date", value: st.end, min: opts.minDate, max: today(), "aria-label": "Go to date",
        onchange: ev => { if (ev.target.value) { st.end = ev.target.value; persist(); reset(); } }});
    const latestBtn = h("button", {onclick: () => { st.end = today(); goTo.value = st.end; persist(); reset(); }}, "Latest");
    const symSel = h("select", {"aria-label": "Symbol", onchange: ev => { st.symbol = ev.target.value; persist(); reset(); }},
        opts.symbols.map(s => h("option", {selected: s === st.symbol}, s)));

    root.replaceChildren(
        h("div", {class: "pc-toolbar"}, symSel, tfSeg, h("span", {class: "pc-range"}, h("span", {}, "Go to"), goTo, latestBtn)),
        h("div", {class: "pc-toolbar"}, indEl),
        h("div", {class: "pc-wrap"}, chartEl, legendEl),
        noteEl);
    renderTf();
    renderInds();

    function makeChart() {
        const L = LWC();
        chart = L.createChart(chartEl, {
            autoSize: true,
            layout: {background: {type: L.ColorType.Solid, color: "#141a24"}, textColor: "#8b95a7",
                     fontFamily: "JetBrains Mono, ui-monospace, monospace", fontSize: 11,
                     panes: {separatorColor: "#232c3a", separatorHoverColor: "#2e3949"}},
            grid: {vertLines: {color: "#1b2230"}, horzLines: {color: "#1b2230"}},
            crosshair: {mode: L.CrosshairMode.Normal,
                        vertLine: {color: "#5d6778", labelBackgroundColor: "#2e3949"},
                        horzLine: {color: "#5d6778", labelBackgroundColor: "#2e3949"}},
            rightPriceScale: {borderColor: "#232c3a"},
            timeScale: {borderColor: "#232c3a", timeVisible: true, secondsVisible: false, rightOffset: 4,
                tickMarkFormatter: (t, type) => {
                    const d = new Date(t * 1000);
                    if (type === L.TickMarkType.Year) return etYear.format(d);
                    if (type === L.TickMarkType.Month) return etMonth.format(d);
                    if (type === L.TickMarkType.DayOfMonth) return etDay.format(d);
                    return etTime.format(d);
                }},
            localization: {timeFormatter: t => {
                const d = new Date(t * 1000);
                return st.tf === "1D" ? etDate.format(d) : `${etDate.format(d)} ${etTime.format(d)} ET`;
            }},
        });
        candleSeries = chart.addSeries(L.CandlestickSeries, {
            upColor: UP, downColor: DOWN, wickUpColor: UP, wickDownColor: DOWN, borderVisible: false,
            priceLineColor: "#5d6778",
        });
        volSeries = chart.addSeries(L.HistogramSeries, {priceFormat: {type: "volume"}, priceLineVisible: false,
                                                         lastValueVisible: false}, 1);
        chart.panes()[1].setStretchFactor(0.18);
        chart.panes()[0].setStretchFactor(0.82);
        markersApi = L.createSeriesMarkers(candleSeries, []);
        chart.subscribeCrosshairMove(param => renderLegend(param.time == null ? null : indexOf.get(param.time)));
        chart.timeScale().subscribeVisibleLogicalRangeChange(() => maybeExtend());
    }

    let indexOf = new Map();
    let indicatorValues = [];

    function drawIndicators() {
        if (!chart || !data.t.length) return;
        const L = LWC();
        lineSeries.forEach(s => chart.removeSeries(s));
        lineSeries = [];
        for (let p = chart.panes().length - 1; p >= 2; p--) chart.removePane(p);
        indicatorValues = [];
        const t = data.t, c = data.c;
        const line = (values, color, opts2 = {}, pane = 0) => {
            const s = chart.addSeries(L.LineSeries, {color, lineWidth: 2, priceLineVisible: false, lastValueVisible: false,
                                                     crosshairMarkerVisible: false, ...opts2}, pane);
            s.setData(values.map((v, i) => (v == null ? {time: t[i]} : {time: t[i], value: v})));
            lineSeries.push(s);
            return s;
        };
        let ownPane = 1;
        st.indicators.forEach((ind, i) => {
            if (ind.type === "custom") {
                const got = customData.get(customKey(ind));
                if (!got || !got.lines) return;
                const pane = ind.pane === "own" ? ++ownPane : 0;
                const names = Object.keys(got.lines);
                const colors = names.map((_, k) => (pane ? OWN_COLORS : LINE_COLORS)[(k + (pane ? 0 : i)) % 4]);
                names.forEach((name, k) => {
                    const s = line(got.lines[name], colors[k], {lineWidth: 2, lastValueVisible: !!pane}, pane);
                    if (k === 0) {
                        for (const level of ind.levels || []) {
                            s.createPriceLine({price: level, color: "#5d6778", lineWidth: 1, lineStyle: L.LineStyle.Dashed,
                                               axisLabelVisible: false, title: ""});
                        }
                    }
                });
                if (pane) chart.panes()[pane].setStretchFactor(0.22);
                indicatorValues.push({name: label(ind) + (names.length > 1 ? ` (${names.join(", ")})` : ""),
                                      color: colors[0], values: names.map(n => got.lines[n])});
                return;
            }
            const n = periodCandles(ind);
            if (ind.type === "bb") {
                const b = bollinger(c, n, ind.k);
                line(b.up, BAND, {lineWidth: 1});
                line(b.mid, BAND, {lineWidth: 1, lineStyle: L.LineStyle.Dashed});
                line(b.lo, BAND, {lineWidth: 1});
                indicatorValues.push({name: `BB ${n}, ${ind.k}σ`, color: BAND, values: [b.up, b.mid, b.lo]});
            } else {
                const color = LINE_COLORS[i % LINE_COLORS.length];
                const v = ind.type === "sma" ? sma(c, n) : ema(c, n);
                line(v, color);
                indicatorValues.push({name: `${label(ind)} ${n}`, color, values: [v]});
            }
        });
        renderLegend(null);
    }

    function fillsAt(i) {
        if (!fills.length) return [];
        const lo = data.t[i], hi = i + 1 < data.t.length ? data.t[i + 1] : Infinity;
        return fills.filter(f => f[0] >= lo && f[0] < hi);
    }

    function renderLegend(i) {
        if (!data.t.length) { legendEl.replaceChildren(); return; }
        const idx = i == null ? data.t.length - 1 : i;
        const o = data.o[idx], c = data.c[idx];
        const prev = idx > 0 ? data.c[idx - 1] : o;
        const raw = c / prev - 1;
        const chg = Math.abs(raw) < 0.00005 ? 0 : raw;
        const cls = c >= o ? "up" : "down";
        const nodes = [
            h("div", {class: "pc-row"}, h("b", {}, `${st.symbol} · ${st.tf}`),
              ...[["O", o], ["H", data.h[idx]], ["L", data.l[idx]], ["C", c]].map(([k, v]) => h("span", {}, k, " ", h("em", {class: cls}, num(v, 2)))),
              h("span", {class: chg > 0 ? "up" : chg < 0 ? "down" : ""}, (chg > 0 ? "+" : "") + pct(chg)),
              h("span", {}, "Vol ", h("em", {}, int(data.v[idx])))),
            ...indicatorValues.map(ind => h("div", {class: "pc-row"}, h("span", {style: `color:${ind.color}`}, ind.name),
                ...ind.values.map(vs => h("em", {}, vs[idx] == null ? "–" : num(vs[idx], 2))))),
        ];
        for (const f of fillsAt(idx).slice(0, 4)) {
            const adj = f[3] * data.f[idx];
            nodes.push(h("div", {class: "pc-row"}, h("span", {style: `color:${f[2] > 0 ? BUY : SELL}`}, f[2] > 0 ? "Bought" : "Sold"),
                h("em", {}, `${int(Math.abs(f[2]))} @ ${num(f[3], 2)}`),
                Math.abs(adj - f[3]) > 0.005 ? h("span", {}, `(${num(adj, 2)} adjusted)`) : null,
                f[4] != null ? h("span", {class: f[4] >= 0 ? "up" : "down"}, `P&L ${f[4] >= 0 ? "+" : ""}${num(f[4], 2)}`) : null));
        }
        legendEl.replaceChildren(...nodes);
    }

    // The chart holds a contiguous window [lo, hi] of trading dates and grows it in chunks of
    // about CHUNK candles as the view nears either edge.
    // False while a reset is loading, so a timeframe switch keeps a just-chosen Go to date.
    let ready = false;
    let destroyed = false;
    let gen = 0, lo = null, hi = null, moreLeft = false, moreRight = false, busyLeft = false, busyRight = false;

    function chunkDays() {
        const perDay = st.tf === "1D" ? 1 : Math.ceil(390 / TF_MIN[st.tf]);
        return Math.max(4, Math.ceil(CHUNK / perDay * 365 / 252));
    }

    async function fetchRange(a, b) {
        const q = new URLSearchParams({symbol: st.symbol, start: a, end: b, tf: st.tf});
        const customs = st.indicators.filter(i => i.type === "custom");
        const [candles, runFills, ...custom] = await Promise.all([
            api(`/api/candles?${q}`),
            opts.runId ? api(`/api/runs/${opts.runId}/fills?start=${a}&end=${b}`) : Promise.resolve([]),
            ...customs.map(ind => api(`/api/indicators/${ind.id}/series?${q}&params=${encodeURIComponent(JSON.stringify(ind.params))}`)
                .then(r => ({ind, r}), e => ({ind, e}))),
        ]);
        // Line values keyed by candle time, so a chunk lines up even if counts ever differ.
        const lines = new Map();
        for (const {ind, r, e} of custom) {
            if (e) { lines.set(customKey(ind), {error: e}); continue; }
            const at = new Map(r.t.map((t, i) => [t, i]));
            const aligned = {};
            for (const [name, vals] of Object.entries(r.series)) {
                aligned[name] = candles.t.map(t => (at.has(t) ? vals[at.get(t)] : null));
            }
            lines.set(customKey(ind), {lines: aligned});
        }
        return [candles, runFills.filter(f => f[1] === st.symbol), lines];
    }

    function join(x, y) {
        const out = {};
        for (const k of Object.keys(x)) out[k] = x[k].concat(y[k]);
        return out;
    }

    // Merge a chunk's indicator lines into what is loaded, before or after it.
    function joinCustom(chunk, nChunk, prepend) {
        for (const ind of st.indicators.filter(i => i.type === "custom")) {
            const k = customKey(ind);
            const have = customData.get(k), add = chunk.get(k);
            if (!have || have.error || !add || add.error) {
                if (add && add.error) customData.set(k, add);
                continue;
            }
            for (const name of Object.keys(have.lines)) {
                const extra = add.lines[name] || new Array(nChunk).fill(null);
                have.lines[name] = prepend ? extra.concat(have.lines[name]) : have.lines[name].concat(extra);
            }
        }
    }

    function reportCustom() {
        const errs = [];
        for (const ind of st.indicators.filter(i => i.type === "custom")) {
            const got = customData.get(customKey(ind));
            if (got && got.error) {
                errs.push(`${label(ind)}: ${got.error.message}`);
                opts.onIndicatorError?.(ind.id, got.error);
            } else if (got) opts.onIndicatorOk?.(ind.id);
        }
        return errs;
    }

    function setNote() {
        const n = data.t.length;
        const parts = [n ? `${int(n)} candles, ${lo} to ${hi}.` : `No candles between ${lo} and ${hi}.`];
        parts.push(moreLeft ? "Scroll left for older data." : "Start of the data.");
        if (n >= MAX_LOADED) parts.push(`Stopped at ${int(MAX_LOADED)} candles; pick a larger timeframe to see further.`);
        if (opts.runId) parts.push(fills.length ? `${int(fills.length)} fills loaded.` : "No fills in this stretch.");
        if (st.indicators.some(i => i.unit === "min") && st.tf !== exactTf) {
            parts.push(`Strategy indicators are scaled to candles; at ${exactTf} they match the strategy exactly.`);
        }
        parts.push("Prices adjusted for splits and dividends, times in New York.");
        const errs = reportCustom();
        noteEl.textContent = errs.length ? errs.join(" ") : parts.join(" ");
        noteEl.className = errs.length ? "pc-note error" : "pc-note";
    }

    function applyData() {
        indexOf = new Map(data.t.map((t, i) => [t, i]));
        candleSeries.setData(data.t.map((t, i) => ({time: t, open: data.o[i], high: data.h[i], low: data.l[i], close: data.c[i]})));
        volSeries.setData(data.t.map((t, i) => ({time: t, value: data.v[i],
            color: data.c[i] >= data.o[i] ? "rgba(60, 207, 122, 0.35)" : "rgba(240, 106, 106, 0.35)"})));
        const marks = [];
        let k = 0;
        for (const f of fills) {
            while (k + 1 < data.t.length && data.t[k + 1] <= f[0]) k++;
            if (!data.t.length || data.t[k] > f[0]) continue;
            const buy = f[2] > 0;
            marks.push({time: data.t[k], position: buy ? "belowBar" : "aboveBar", shape: buy ? "arrowUp" : "arrowDown",
                        color: buy ? BUY : SELL, text: buy ? "B" : "S"});
        }
        markersApi.setMarkers(marks);
        drawIndicators();
        setNote();
    }

    function showError(e) {
        noteEl.textContent = e.message;
        noteEl.className = "pc-note error";
    }

    async function reset() {
        if (destroyed) return;
        const g = ++gen;
        ready = false;
        busyLeft = busyRight = false;
        const end = st.end > today() ? today() : st.end;
        let start = addDays(end, 1 - chunkDays());
        if (start < opts.minDate) start = opts.minDate;
        noteEl.textContent = "Loading…";
        noteEl.className = "pc-note";
        let got;
        try { got = await fetchRange(start, end); } catch (e) { if (g === gen) showError(e); return; }
        if (g !== gen || destroyed) return;
        if (!chart) makeChart();
        [data, fills, customData] = got;
        lo = start; hi = end;
        moreLeft = start > opts.minDate;
        moreRight = end < today();
        applyData();
        const n = data.t.length;
        chart.timeScale().setVisibleLogicalRange({from: Math.max(0, n - (opts.visible || 160)), to: n + 4});
        ready = true;
        maybeExtend();
    }

    async function extendLeft() {
        if (busyLeft || !moreLeft || data.t.length >= MAX_LOADED) return;
        busyLeft = true;
        const g = gen;
        const b = addDays(lo, -1);
        let a = addDays(b, 1 - chunkDays());
        if (a < opts.minDate) a = opts.minDate;
        let got;
        try { got = await fetchRange(a, b); } catch (e) { busyLeft = false; if (g === gen) showError(e); return; }
        if (g !== gen) return;
        const [c, f, cl] = got;
        const range = chart.timeScale().getVisibleLogicalRange();
        data = join(c, data);
        fills = f.concat(fills);
        joinCustom(cl, c.t.length, true);
        lo = a;
        moreLeft = a > opts.minDate;
        applyData();
        // Prepending shifts every index; move the view by the same amount so nothing jumps.
        if (range && c.t.length) {
            chart.timeScale().setVisibleLogicalRange({from: range.from + c.t.length, to: range.to + c.t.length});
        }
        busyLeft = false;
        maybeExtend();
    }

    async function extendRight() {
        if (busyRight || !moreRight || data.t.length >= MAX_LOADED) return;
        busyRight = true;
        const g = gen;
        const a = addDays(hi, 1);
        let b = addDays(a, chunkDays() - 1);
        if (b > today()) b = today();
        let got;
        try { got = await fetchRange(a, b); } catch (e) { busyRight = false; if (g === gen) showError(e); return; }
        if (g !== gen) return;
        const [c, f, cl] = got;
        const range = chart.timeScale().getVisibleLogicalRange();
        data = join(data, c);
        fills = fills.concat(f);
        joinCustom(cl, c.t.length, false);
        hi = b;
        moreRight = b < today();
        applyData();
        if (range) chart.timeScale().setVisibleLogicalRange(range);
        busyRight = false;
        maybeExtend();
    }

    function maybeExtend() {
        if (!chart) return;
        const r = chart.timeScale().getVisibleLogicalRange();
        if (!r) return;
        if (r.from < EDGE) extendLeft();
        if (r.to > data.t.length - EDGE) extendRight();
    }

    // Read-only view of what is loaded, for tests and the browser console.
    root.pcState = () => {
        const r = chart && chart.timeScale().getVisibleLogicalRange();
        const at = i => (data.t[Math.max(0, Math.min(data.t.length - 1, Math.round(i)))] ?? null);
        let ordered = true;
        for (let i = 1; i < data.t.length; i++) if (data.t[i] <= data.t[i - 1]) { ordered = false; break; }
        return {n: data.t.length, lo, hi, moreLeft, moreRight, ordered, fills: fills.length, tf: st.tf,
                firstVisible: r ? at(r.from) : null, lastVisible: r ? at(r.to) : null};
    };
    api("/api/strategies").then(list => { customList = list.filter(x => x.kind === "indicator"); renderInds(); }).catch(() => {});
    reset();
    return {refresh: reset, updateCustom, destroy() {
        // Bumping gen makes any load still in flight drop its result instead of drawing on a
        // chart that no longer exists.
        destroyed = true;
        gen++;
        if (chart) chart.remove();
        chart = null;
    }};
}
