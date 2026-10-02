from datetime import date

from btest.ui.server import _clean, monthly_returns


def test_monthly_returns_chain_from_month_ends():
    eq = [(date(2024, 1, 2), 100.0, None), (date(2024, 1, 31), 110.0, None),
          (date(2024, 2, 1), 105.0, None), (date(2024, 2, 29), 99.0, None)]
    out = monthly_returns(eq)
    assert [r[:2] for r in out] == [[2024, 1], [2024, 2]]
    assert round(out[0][2], 6) == 0.1 and round(out[1][2], 6) == round(99 / 110 - 1, 6)


def test_clean_replaces_nan_and_inf():
    assert _clean({"a": float("nan"), "b": [float("inf"), 1.0]}) == {"a": None, "b": [None, 1.0]}

