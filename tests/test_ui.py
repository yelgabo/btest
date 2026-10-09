from datetime import date

import pytest

from btest.ui.server import _clean, monthly_returns


def test_monthly_returns_chain_from_month_ends():
    eq = [(date(2024, 1, 2), 100.0, None), (date(2024, 1, 31), 110.0, None),
          (date(2024, 2, 1), 105.0, None), (date(2024, 2, 29), 99.0, None)]
    out = monthly_returns(eq)
    assert [r[:2] for r in out] == [[2024, 1], [2024, 2]]
    assert round(out[0][2], 6) == 0.1 and round(out[1][2], 6) == round(99 / 110 - 1, 6)


def test_clean_replaces_nan_and_inf():
    assert _clean({"a": float("nan"), "b": [float("inf"), 1.0]}) == {"a": None, "b": [None, 1.0]}



def login_client(auth, ip):
    from starlette.testclient import TestClient
    return TestClient(auth, base_url="https://testserver", client=(ip, 1))


def test_login_limit_holds_across_addresses_and_forgets_old_failures(monkeypatch):
    from btest.ui import server

    async def app(scope, receive, send):
        raise AssertionError("not reached")

    now = [1_000_000.0]
    monkeypatch.setattr(server.time, "time", lambda: now[0])
    auth = server.SessionAuth(app, "pw")
    for i in range(server.MAX_FAILS_ALL):
        c = login_client(auth, f"10.1.0.{i}")
        assert c.post("/login", data={"password": "no"}).status_code == 401
    assert len(auth.fails) == server.MAX_FAILS_ALL
    fresh = login_client(auth, "10.2.0.1")
    assert fresh.post("/login", data={"password": "pw"}).status_code == 429

    now[0] += server.FAIL_WINDOW_S + 1
    r = fresh.post("/login", data={"password": "pw"}, follow_redirects=False)
    assert r.status_code == 303
    assert auth.fails == {} and auth.all_fails == []


def test_ui_refuses_to_serve_off_loopback_without_a_password(monkeypatch):
    from btest.ui.server import check_exposure
    monkeypatch.delenv("BTEST_UI_PASSWORD", raising=False)
    for host in ("127.0.0.1", "::1", "[::1]", "localhost"):
        check_exposure(host)
    for host in ("0.0.0.0", "::", "192.168.1.5", "example.com"):
        with pytest.raises(SystemExit, match="BTEST_UI_PASSWORD"):
            check_exposure(host)
    monkeypatch.setenv("BTEST_UI_PASSWORD", "pw")
    check_exposure("0.0.0.0")
