// Candlestick chart with indicator overlays and a run's fills, on TradingView's
// lightweight-charts (loaded as a global from the CDN in index.html).

const LWC = () => window.LightweightCharts;
const TF_MIN = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "1D": 390};
const UP = "#3ccf7a", DOWN = "#f06a6a", BUY = "#3987e5", SELL = "#e8833a";
const LINE_COLORS = ["#3987e5", "#c98500", "#199e70", "#d55181"];
const BAND = "#9085e9";

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

// Population standard deviation, the same definition the z-score strategy uses.
function bollinger(c, n, k) {
    const mid = sma(c, n), up = new Array(c.length).fill(null), lo = new Array(c.length).fill(null);
    for (let i = n - 1; i < c.length; i++) {
        let ss = 0;
        for (let j = i - n + 1; j <= i; j++) ss += (c[j] - mid[i]) ** 2;
        const sd = Math.sqrt(ss / n);
        up[i] = mid[i] + k * sd;
        lo[i] = mid[i] - k * sd;
    }
    return {mid, up, lo};
}

const store = {
    get(key, fallback) { try { const v = localStorage.getItem("btest.chart." + key); return v ? JSON.parse(v) : fallback; } catch { return fallback; } },
    set(key, value) { try { localStorage.setItem("btest.chart." + key, JSON.stringify(value)); } catch { /* private mode */ } },
};

// Indicators the strategy itself uses, read from its params. Lengths are in minutes so
// they stay true to the strategy whatever the candle size.
export function presetsFor(params) {
    const p = params || {};
    if (typeof p.fast === "number" && typeof p.slow === "number") {
        return [{type: "sma", len: p.fast, unit: "min"}, {type: "sma", len: p.slow, unit: "min"}];
    }
    if (typeof p.window === "number" && typeof p.entry_z === "number") {
        return [{type: "bb", len: p.window, unit: "min", k: p.entry_z}];
    }
    return [{type: "sma", len: 20, unit: "c"}];
}

export function priceChart(root, opts, ui) {
    const {h, api, num, int, pct} = ui;
    const key = opts.storeKey || "free";
    const saved = store.get(key, {});
    const st = {
        symbol: saved.symbol && opts.symbols.includes(saved.symbol) ? saved.symbol : opts.symbol,
        tf: saved.tf || opts.tf,
        start: saved.start || opts.start,
        end: saved.end || opts.end,
        indicators: saved.indicators || opts.indicators,
    };
    const persist = () => store.set(key, st);
    let data = null, fills = [], chart = null, candleSeries = null, volSeries = null, markersApi = null;
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
        const name = {sma: "SMA", ema: "EMA", bb: "BB"}[ind.type];
        return name;
    }

    function renderTf() {
        tfSeg.replaceChildren(...Object.keys(TF_MIN).map(tf => h("button", {"aria-pressed": String(tf === st.tf), onclick: () => {
            st.tf = tf; persist(); renderTf(); renderInds(); load();
        }}, tf)));
    }

    function renderInds() {
        indEl.replaceChildren(...st.indicators.map((ind, i) => {
            const color = ind.type === "bb" ? BAND : LINE_COLORS[i % LINE_COLORS.length];
            const lenInput = h("input", {type: "number", min: 1, step: 1, value: ind.len, "aria-label": `${label(ind)} length`,
                onchange: ev => { const v = +ev.target.value; if (v >= 1) { ind.len = v; persist(); renderInds(); drawIndicators(); } }});
            const approx = ind.unit === "min" && st.tf !== "1m";
            return h("span", {class: "pc-chip", style: `--c:${color}`, title: approx
                ? `${ind.len} minutes ≈ ${periodCandles(ind)} ${st.tf} candles. Switch to 1m to match the strategy exactly.` : null},
                h("b", {}, label(ind)), lenInput, h("small", {}, ind.unit === "min" ? "min" : "bars"),
                ind.type === "bb" ? [h("input", {type: "number", min: 0.1, step: 0.1, value: ind.k, "aria-label": "Band width in standard deviations",
                    onchange: ev => { const v = +ev.target.value; if (v > 0) { ind.k = v; persist(); drawIndicators(); } }}), h("small", {}, "σ")] : null,
                h("button", {class: "icon", "aria-label": `Remove ${label(ind)}`, onclick: () => {
                    st.indicators.splice(i, 1); persist(); renderInds(); drawIndicators();
                }}, "×"));
        }), h("select", {"aria-label": "Add indicator", onchange: ev => {
            const type = ev.target.value;
            ev.target.value = "";
            if (!type) return;
            st.indicators.push(type === "bb" ? {type, len: 20, unit: "c", k: 2} : {type, len: type === "ema" ? 9 : 20, unit: "c"});
            persist(); renderInds(); drawIndicators();
        }}, h("option", {value: ""}, "Add indicator"), h("option", {value: "sma"}, "SMA, simple moving average"),
            h("option", {value: "ema"}, "EMA, exponential moving average"), h("option", {value: "bb"}, "Bollinger bands")));
    }

    const date = k => h("input", {type: "date", value: st[k], min: opts.minDate, "aria-label": k === "start" ? "From" : "Until",
        onchange: ev => { st[k] = ev.target.value; persist(); load(); }});
    const symSel = h("select", {"aria-label": "Symbol", onchange: ev => { st.symbol = ev.target.value; persist(); load(); }},
        opts.symbols.map(s => h("option", {selected: s === st.symbol}, s)));

    root.replaceChildren(
        h("div", {class: "pc-toolbar"}, symSel, tfSeg, h("span", {class: "pc-range"}, date("start"), h("span", {}, "to"), date("end"))),
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
    }

    let indexOf = new Map();
    let indicatorValues = [];

    function drawIndicators() {
        if (!chart || !data) return;
        const L = LWC();
        lineSeries.forEach(s => chart.removeSeries(s));
        lineSeries = [];
        indicatorValues = [];
        const t = data.t, c = data.c;
        const line = (values, color, opts2 = {}) => {
            const s = chart.addSeries(L.LineSeries, {color, lineWidth: 2, priceLineVisible: false, lastValueVisible: false,
                                                     crosshairMarkerVisible: false, ...opts2});
            s.setData(values.map((v, i) => (v == null ? {time: t[i]} : {time: t[i], value: v})));
            lineSeries.push(s);
        };
        st.indicators.forEach((ind, i) => {
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
        if (!data || !data.t.length) { legendEl.replaceChildren(); return; }
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

    async function load() {
        const token = ++loadToken;
        noteEl.textContent = "Loading…";
        noteEl.className = "pc-note";
        let candles, runFills = [];
        try {
            const q = new URLSearchParams({symbol: st.symbol, start: st.start, end: st.end, tf: st.tf});
            [candles, runFills] = await Promise.all([
                api(`/api/candles?${q}`),
                opts.runId ? api(`/api/runs/${opts.runId}/fills?start=${st.start}&end=${st.end}`) : Promise.resolve([]),
            ]);
        } catch (e) {
            if (token !== loadToken) return;
            noteEl.textContent = e.message;
            noteEl.className = "pc-note error";
            return;
        }
        if (token !== loadToken) return;
        if (!chart) makeChart();
        data = candles;
        fills = runFills.filter(f => f[1] === st.symbol);
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
                        color: buy ? BUY : SELL, text: fills.length <= 300 ? (buy ? "B" : "S") : undefined});
        }
        markersApi.setMarkers(marks);
        drawIndicators();
        const n = data.t.length;
        if (n) chart.timeScale().setVisibleLogicalRange({from: Math.max(0, n - (opts.visible || 160)), to: n + 4});
        const parts = [`${int(n)} candles, prices adjusted for splits and dividends, times in New York.`];
        if (opts.runId) parts.push(fills.length ? `${int(fills.length)} fills in this range.` : "No fills in this range.");
        if (st.indicators.some(i => i.unit === "min") && st.tf !== "1m") {
            parts.push("Strategy indicators are scaled to candles; at 1m they match the strategy exactly.");
        }
        noteEl.textContent = parts.join(" ");
    }

    load();
    return {destroy() { if (chart) chart.remove(); chart = null; }};
}
