import hashlib
import hmac
import json
import os
import time
from datetime import UTC, date, datetime, timedelta
from importlib import resources

import httpx
import psycopg
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware.gzip import GZipMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from btest import bars, config, db, lab
from btest.engine import Costs

STATIC = resources.files("btest.ui") / "static"
SUMMARY_KEYS = ["total_return", "cagr", "sharpe", "sortino", "max_drawdown", "ann_vol",
                "fills", "exposure", "win_rate", "turnover", "costs", "end_equity"]


def _json_default(v):
    if isinstance(v, datetime):
        return v.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(v, date):
        return v.isoformat()
    raise TypeError(f"not JSON serializable: {type(v).__name__}")


class JSON(Response):
    media_type = "application/json"

    def render(self, content) -> bytes:
        return json.dumps(content, default=_json_default, allow_nan=False).encode()


def _clean(v):
    """JSON has no NaN or infinity; send null instead."""
    if isinstance(v, float) and v != v or v in (float("inf"), float("-inf")):
        return None
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_clean(x) for x in v]
    return v


def create_app() -> Starlette:
    settings = config.load(need_alpaca=False)
    with psycopg.connect(settings.database_url) as c:
        db.migrate(c)
    holdout = datetime.combine(settings.holdout_start, datetime.min.time(), UTC)

    def conn() -> psycopg.Connection:
        return psycopg.connect(settings.database_url)

    async def runs(request: Request):
        with conn() as c:
            rows = c.execute(
                "SELECT r.id, r.created_at, r.strategy, r.symbols, r.start_ts, r.end_ts, r.params, "
                "r.metrics, r.benchmark_metrics, r.git_commit, r.git_dirty, v.strategy_id, "
                "v.version, coalesce(r.config->>'timeframe', '1m') "
                "FROM runs.run r LEFT JOIN lab.strategy_version v "
                "ON v.id = r.strategy_version_id ORDER BY r.id DESC"
            ).fetchall()
        return JSON(_clean([{
            "id": r[0], "created_at": r[1], "strategy": r[2], "symbols": r[3],
            "start": r[4], "end": r[5], "params": r[6],
            "metrics": {k: r[7].get(k) for k in SUMMARY_KEYS},
            "benchmark": {k: (r[8] or {}).get(k) for k in SUMMARY_KEYS},
            "git_commit": r[9], "git_dirty": r[10], "holdout": r[5] > holdout,
            "strategy_id": r[11], "version": r[12], "timeframe": r[13],
        } for r in rows]))

    async def run_detail(request: Request):
        run_id = request.path_params["id"]
        with conn() as c:
            r = c.execute(
                "SELECT id, created_at, strategy, strategy_sha256, symbols, start_ts, end_ts, "
                "params, config, metrics, benchmark_metrics, git_commit, git_dirty, duration_s, "
                "(SELECT strategy_id FROM lab.strategy_version v WHERE v.id = strategy_version_id), "
                "(SELECT version FROM lab.strategy_version v WHERE v.id = strategy_version_id) "
                "FROM runs.run WHERE id = %s", (run_id,),
            ).fetchone()
            if r is None:
                return JSON({"error": f"No run {run_id}."}, status_code=404)
            equity = c.execute(
                "SELECT date, equity, benchmark FROM runs.equity WHERE run_id = %s ORDER BY date",
                (run_id,),
            ).fetchall()
            fill_count = c.execute("SELECT count(*) FROM runs.fill WHERE run_id = %s",
                                   (run_id,)).fetchone()[0]
            fills = c.execute(
                "SELECT ts, symbol, qty, price, slippage + fees + commission, realized_pnl "
                "FROM runs.fill WHERE run_id = %s ORDER BY seq DESC LIMIT 200", (run_id,),
            ).fetchall()
        return JSON(_clean({
            "id": r[0], "created_at": r[1], "strategy": r[2], "strategy_sha256": r[3],
            "symbols": r[4], "start": r[5], "end": r[6], "params": r[7], "config": r[8],
            "metrics": r[9], "benchmark": r[10] or {}, "git_commit": r[11], "git_dirty": r[12],
            "duration_s": r[13], "holdout": r[6] > holdout, "strategy_id": r[14],
            "version": r[15],
            "equity": [[d, round(e, 2), None if b is None else round(b, 2)] for d, e, b in equity],
            "monthly": monthly_returns(equity),
            "fill_count": fill_count,
            "fills": [list(f) for f in fills],
        }))

    async def sweeps(request: Request):
        with conn() as c:
            rows = c.execute(
                "SELECT s.id, s.created_at, s.strategy, s.symbol, s.start_ts, s.end_ts, s.grid, "
                "s.fixed_params, s.combos, s.skipped, s.duration_s, "
                "(SELECT max((r.metrics->>'sharpe')::float) FROM runs.sweep_result r "
                " WHERE r.sweep_id = s.id) FROM runs.sweep s ORDER BY s.id DESC"
            ).fetchall()
        return JSON(_clean([{
            "id": r[0], "created_at": r[1], "strategy": r[2], "symbol": r[3], "start": r[4],
            "end": r[5], "grid": r[6], "fixed": r[7], "combos": r[8], "skipped": r[9],
            "duration_s": r[10], "best_sharpe": r[11],
        } for r in rows]))

    async def sweep_detail(request: Request):
        sweep_id = request.path_params["id"]
        with conn() as c:
            s = c.execute(
                "SELECT id, created_at, strategy, symbol, start_ts, end_ts, holdout_start, grid, "
                "fixed_params, config, combos, skipped, duration_s, git_commit, git_dirty "
                "FROM runs.sweep WHERE id = %s", (sweep_id,),
            ).fetchone()
            if s is None:
                return JSON({"error": f"No sweep {sweep_id}."}, status_code=404)
            results = c.execute(
                "SELECT params, metrics FROM runs.sweep_result WHERE sweep_id = %s ORDER BY seq",
                (sweep_id,),
            ).fetchall()
        return JSON(_clean({
            "id": s[0], "created_at": s[1], "strategy": s[2], "symbol": s[3], "start": s[4],
            "end": s[5], "holdout_start": s[6], "grid": s[7], "fixed": s[8], "config": s[9],
            "combos": s[10], "skipped": s[11], "duration_s": s[12], "git_commit": s[13],
            "git_dirty": s[14],
            "results": [{"params": p, "metrics": m} for p, m in results],
        }))

    async def data(request: Request):
        with conn() as c:
            actions = c.execute(
                "SELECT y.ticker, "
                "(SELECT count(*) FROM market.split s WHERE s.symbol_id = y.id), "
                "(SELECT count(*) FROM market.dividend d WHERE d.symbol_id = y.id), "
                "(SELECT json_agg(json_build_object('ex_date', s.ex_date, 'ratio', "
                " s.new_rate / s.old_rate) ORDER BY s.ex_date) FROM market.split s "
                " WHERE s.symbol_id = y.id), "
                "(SELECT max(d.ex_date) FROM market.dividend d WHERE d.symbol_id = y.id) "
                "FROM market.symbol y ORDER BY y.ticker"
            ).fetchall()
            cov = {r[0]: r[1:] for r in c.execute(
                "SELECT symbol, bars, regular_bars, first_ts, last_ts FROM market.coverage")}
            rate = c.execute("SELECT date, value FROM market.rate WHERE series = 'DTB3' "
                             "ORDER BY date DESC LIMIT 1").fetchone()
        symbols = []
        for ticker, n_splits, n_divs, split_list, last_div in actions:
            n, regular, first, last = cov.get(ticker, (0, 0, None, None))
            symbols.append({
                "symbol": ticker, "bars": n, "regular_bars": regular, "first": first,
                "last": last, "splits": split_list or [], "dividends": n_divs,
                "last_dividend": last_div,
            })
        return JSON({
            "symbols": symbols,
            "holdout_start": settings.holdout_start,
            "history_start": settings.history_start,
            "risk_free": {"series": "DTB3", "date": rate[0], "value": rate[1]} if rate else None,
        })

    async def body(request: Request) -> dict:
        try:
            data = await request.json()
        except ValueError:
            data = None
        if not isinstance(data, dict):
            raise ValueError("Send a JSON object.")
        return data

    def bad(msg: str, status: int = 400):
        return JSON({"error": msg}, status_code=status)

    async def lab_config(request: Request):
        return JSON({
            "symbols": settings.symbols, "history_start": settings.history_start,
            "holdout_start": settings.holdout_start, "template": lab.TEMPLATE,
            "defaults": {"cash": 100_000.0, "slippage_bps": Costs().slippage_bps,
                         "commission_per_share": Costs().commission_per_share,
                         "sec_fee_rate": Costs().sec_fee_rate, "allow_short": False},
        })

    async def strategies(request: Request):
        if request.method == "POST":
            try:
                data = await body(request)
                with conn() as c:
                    sid = lab.create(c, str(data.get("name", "")), data.get("code"),
                                     str(data.get("kind", "strategy")))
            except ValueError as e:
                return bad(str(e))
            return JSON({"id": sid}, status_code=201)
        with conn() as c:
            return JSON(lab.list_strategies(c))

    async def strategy(request: Request):
        sid = request.path_params["id"]
        try:
            if request.method == "GET":
                v = request.query_params.get("version")
                with conn() as c:
                    s = lab.get(c, sid, int(v) if v and v.isdigit() else None)
                return JSON(_clean(s)) if s else bad(f"No strategy {sid}.", 404)
            if request.method == "DELETE":
                with conn() as c:
                    lab.archive(c, sid)
                return JSON({"ok": True})
            data = await body(request)
            with conn() as c:
                if request.method == "PATCH":
                    lab.rename(c, sid, str(data.get("name", "")))
                    return JSON({"ok": True})
                code = data.get("code")
                if not isinstance(code, str) or len(code) > 200_000:
                    return bad("code must be text under 200 kB.")
                version = lab.save(c, sid, code, int(data.get("base_version", 0)))
                return JSON(_clean(lab.get(c, sid, version)))
        except LookupError as e:
            return bad(str(e), 404)
        except ValueError as e:
            return bad(str(e), 409 if "Reload" in str(e) else 400)

    async def jobs(request: Request):
        try:
            data = await body(request)
            sid, kind = int(data.get("strategy_id", 0)), str(data.get("kind", ""))
            with conn() as c:
                s = lab.get(c, sid, data.get("version"))
                if s is None:
                    return bad("That strategy or version does not exist.", 404)
                if s["kind"] != "strategy":
                    return bad("Indicators are not run as backtests; add them to a chart.")
                if s["parse_error"]:
                    line = f" (line {s['parse_error_line']})" if s["parse_error_line"] else ""
                    return bad(f"{s['parse_error']}{line}")
                spec = lab.validate_spec(kind, data.get("spec") or {}, settings, s["has_signals"])
                jid = lab.submit(c, s["version_id"], kind, spec)
        except (TypeError, ValueError) as e:
            return bad(str(e))
        return JSON({"id": jid}, status_code=201)

    async def job_detail(request: Request):
        with conn() as c:
            j = lab.job(c, request.path_params["id"])
        return JSON(_clean(j)) if j else bad("No such job.", 404)

    async def strategy_jobs(request: Request):
        with conn() as c:
            return JSON(_clean(lab.recent_jobs(c, request.path_params["id"])))

    bars_url = os.environ.get("BTEST_BARS_URL")
    bars_token = os.environ.get("BTEST_INTERNAL_TOKEN", "")

    async def candles(request: Request):
        q = request.query_params
        args = {k: q.get(k, "") for k in ("symbol", "start", "end", "tf")}
        try:
            start, end = bars.check(args["symbol"].upper(), args["start"], args["end"],
                                    args["tf"], settings.symbols)
        except ValueError as e:
            return bad(str(e))
        if bars_url:
            # The bars live on the worker's volume; it serves them on the private network.
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.get(f"{bars_url}/bars", params=args,
                                     headers={"X-Btest-Token": bars_token})
            return Response(r.content, status_code=r.status_code, media_type="application/json")
        with conn() as c:
            sym = args["symbol"].upper()
            out = bars.candles(settings.data_dir, sym, start, end, args["tf"],
                               db.get_splits(c, sym), db.get_dividends(c, sym))
        return JSON(out)

    async def indicator_series(request: Request):
        q = request.query_params
        try:
            params = json.loads(q.get("params") or "{}")
            if not isinstance(params, dict):
                raise ValueError
        except ValueError:
            return bad("params must be a JSON object.")
        with conn() as c:
            v = q.get("version")
            s = lab.get(c, request.path_params["id"], int(v) if v and v.isdigit() else None)
        if s is None or s["kind"] != "indicator":
            return bad("No such indicator.", 404)
        body = {"code": s["code"], "name": s["name"], "params": params,
                "symbol": q.get("symbol", "").upper(), "start": q.get("start", ""),
                "end": q.get("end", ""), "tf": q.get("tf", "")}
        if bars_url:
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(f"{bars_url}/indicator", json=body,
                                      headers={"X-Btest-Token": bars_token})
            return Response(r.content, status_code=r.status_code, media_type="application/json")
        try:
            start, end = bars.check(body["symbol"], body["start"], body["end"], body["tf"],
                                    settings.symbols)
        except ValueError as e:
            return bad(str(e))
        from btest import indicator_run
        out = await run_in_threadpool(indicator_run.series, settings, conn, s["code"], s["name"],
                                      params, body["symbol"], start, end, body["tf"])
        return JSON(_clean(out), status_code=422 if out.get("error") else 200)

    async def run_fills(request: Request):
        q = request.query_params
        try:
            start = datetime.fromisoformat(q.get("start", "")).replace(tzinfo=UTC)
            end = datetime.fromisoformat(q.get("end", "")).replace(tzinfo=UTC) + timedelta(days=1)
        except ValueError:
            return bad("start and end must be dates.")
        with conn() as c:
            rows = c.execute(
                "SELECT extract(epoch FROM ts)::bigint, symbol, qty, price, realized_pnl "
                "FROM runs.fill WHERE run_id = %s AND ts >= %s AND ts < %s ORDER BY seq",
                (request.path_params["id"], start, end),
            ).fetchall()
        return JSON(_clean([list(r) for r in rows]))

    async def index(request: Request):
        return FileResponse(STATIC / "index.html")

    app = Starlette(routes=[
        Route("/", index),
        Route("/api/runs", runs),
        Route("/api/runs/{id:int}", run_detail),
        Route("/api/sweeps", sweeps),
        Route("/api/sweeps/{id:int}", sweep_detail),
        Route("/api/data", data),
        Route("/api/lab", lab_config),
        Route("/api/strategies", strategies, methods=["GET", "POST"]),
        Route("/api/strategies/{id:int}", strategy, methods=["GET", "PUT", "PATCH", "DELETE"]),
        Route("/api/strategies/{id:int}/jobs", strategy_jobs),
        Route("/api/jobs", jobs, methods=["POST"]),
        Route("/api/jobs/{id:int}", job_detail),
        Route("/api/candles", candles),
        Route("/api/indicators/{id:int}/series", indicator_series),
        Route("/api/runs/{id:int}/fills", run_fills),
        Mount("/static", StaticFiles(directory=str(STATIC)), name="static"),
    ])
    app.add_middleware(GZipMiddleware, minimum_size=2000)
    app.add_middleware(RequireHeader)
    password = os.environ.get("BTEST_UI_PASSWORD")
    if password:
        app.add_middleware(SessionAuth, password=password)
    return app


SESSION_COOKIE = "btest_session"
SESSION_DAYS = 14
MAX_FAILS = 10
FAIL_WINDOW_S = 15 * 60


class SessionAuth:
    """Login page plus a signed, expiring session cookie. The signing key is derived from
    BTEST_UI_PASSWORD, so changing the password signs everyone out."""

    OPEN = {"/login", "/favicon.ico"}

    def __init__(self, app, password: str):
        self.app = app
        self.password = password.encode()
        self.key = hashlib.sha256(b"btest-session:" + self.password).digest()
        self.fails: dict[str, list[float]] = {}

    def sign(self, expires: int) -> str:
        mac = hmac.new(self.key, str(expires).encode(), hashlib.sha256).hexdigest()
        return f"{expires}.{mac}"

    def valid(self, cookie: str | None) -> bool:
        if not cookie or "." not in cookie:
            return False
        expires, _, _ = cookie.partition(".")
        return (expires.isdigit() and int(expires) > time.time()
                and hmac.compare_digest(cookie, self.sign(int(expires))))

    def throttled(self, ip: str) -> bool:
        now = time.time()
        recent = [t for t in self.fails.get(ip, []) if now - t < FAIL_WINDOW_S]
        self.fails[ip] = recent
        return len(recent) >= MAX_FAILS

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope, receive)
        path = scope["path"]
        if path == "/login":
            return await self.login(request)(scope, receive, send)
        if path == "/logout":
            resp = RedirectResponse("/login", status_code=303)
            resp.delete_cookie(SESSION_COOKIE)
            return await resp(scope, receive, send)
        if not self.valid(request.cookies.get(SESSION_COOKIE)):
            if path.startswith("/api/"):
                resp = JSON({"error": "Signed out. Reload the page to sign in."}, status_code=401)
            else:
                resp = RedirectResponse("/login", status_code=303)
            return await resp(scope, receive, send)
        return await self.app(scope, receive, send)

    def login(self, request: Request):
        async def handler(scope, receive, send):
            ip = request.client.host if request.client else "?"
            error = ""
            if request.method == "POST":
                if self.throttled(ip):
                    resp = HTMLResponse(login_page("Too many wrong passwords. Wait 15 minutes."),
                                        status_code=429)
                    return await resp(scope, receive, send)
                form = await request.form()
                given = str(form.get("password", "")).encode()
                if hmac.compare_digest(given, self.password):
                    self.fails.pop(ip, None)
                    expires = int(time.time()) + SESSION_DAYS * 86400
                    resp = RedirectResponse("/", status_code=303)
                    resp.set_cookie(SESSION_COOKIE, self.sign(expires),
                                    max_age=SESSION_DAYS * 86400, httponly=True, samesite="strict",
                                    secure=request.url.scheme == "https")
                    return await resp(scope, receive, send)
                self.fails.setdefault(ip, []).append(time.time())
                error = "That password is wrong."
            resp = HTMLResponse(login_page(error), status_code=401 if error else 200)
            await resp(scope, receive, send)
        return handler


class RequireHeader:
    """Every API write must carry X-Btest. Browsers will not add a custom header to a
    cross-site request without a CORS preflight, which this server never approves."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (scope["type"] == "http" and scope["method"] not in ("GET", "HEAD", "OPTIONS")
                and scope["path"].startswith("/api/")
                and dict(scope["headers"]).get(b"x-btest") != b"1"):
            resp = JSON({"error": "Missing X-Btest header."}, status_code=403)
            return await resp(scope, receive, send)
        return await self.app(scope, receive, send)


def login_page(error: str) -> str:
    template = (STATIC / "login.html").read_text()
    msg = f'<p class="err" role="alert">{error}</p>' if error else ""
    return template.replace("__ERROR__", msg)


def monthly_returns(equity: list[tuple]) -> list[list]:
    """[year, month, return] from month-end equity; the first month is measured from the
    first day's equity."""
    out = []
    prev = equity[0][1] if equity else None
    for i, (d, e, _) in enumerate(equity):
        nxt = equity[i + 1][0] if i + 1 < len(equity) else None
        if nxt is None or (nxt.year, nxt.month) != (d.year, d.month):
            out.append([d.year, d.month, e / prev - 1 if prev else None])
            prev = e
    return out
