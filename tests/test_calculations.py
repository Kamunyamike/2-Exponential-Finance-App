"""Unit tests for the calculation engine and database layer.

Run with:  python -m pytest -q
"""

import sys
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import calculations as calc  # noqa: E402
from database import TrackerDB  # noqa: E402

P, M = Fraction(10), Fraction(2)


def test_documented_progression():
    expected = [10, 20, 40, 80, 160, 320]
    assert [calc.projected_balance(P, M, n) for n in range(6)] == expected


def test_exact_integer_arithmetic_for_large_weeks():
    value = calc.projected_balance(P, M, 520)
    assert value == 10 * 2 ** 520
    assert value.denominator == 1


def test_schedule_matches_formula():
    rows = calc.growth_schedule(P, M, 8)
    assert len(rows) == 9
    for row in rows[1:]:
        assert row.closing == P * M ** row.week
        assert row.opening * M == row.closing
        assert row.weekly_target == row.closing - row.opening
    assert rows[5].growth_pct == 3100


def test_week_summary():
    s = calc.week_summary(P, M, 5)
    assert (s.projected, s.previous, s.weekly_gain, s.total_increase) == (320, 160, 160, 310)
    assert s.growth_pct == 3100
    assert calc.week_summary(P, M, 0).previous is None


@pytest.mark.parametrize("bad", [-1, 521, 2.5, "abc", None, True])
def test_invalid_weeks_rejected(bad):
    with pytest.raises(calc.ValidationError):
        calc.validate_week(bad)


@pytest.mark.parametrize("bad", [0, -5, "x", 2_000_000_000, float("nan")])
def test_invalid_capital_rejected(bad):
    with pytest.raises(calc.ValidationError):
        calc.validate_capital(bad)


@pytest.mark.parametrize("bad", [1, 0.5, 11, "1e999999"])
def test_invalid_multiplier_rejected(bad):
    with pytest.raises(calc.ValidationError):
        calc.validate_multiplier(bad)


def test_non_integer_multiplier_is_exact():
    m = calc.validate_multiplier(1.1)
    assert m == Fraction(11, 10)
    assert calc.projected_balance(P, m, 2) == Fraction(121, 10)


def test_currency_formatting():
    assert calc.format_usd(Fraction(1234567, 100)) == "$12,345.67"
    assert calc.format_usd(Fraction(5, 1000)) == "$0.01"          # half-up rounding
    assert calc.format_usd(-12) == "-$12.00"
    assert calc.format_usd(160, signed=True) == "+$160.00"
    assert calc.format_usd(10 * 2 ** 30, compact=True) == "$10.74B"
    assert calc.format_usd(10 * 2 ** 520).startswith("$3.43 × 10^157")
    assert calc.format_usd("$1,250.50") == "$1,250.50"
    assert calc.format_pct(3100) == "3,100.00%"


def test_safe_float_handles_overflow():
    assert calc.safe_float(Fraction(320)) == 320.0
    assert calc.safe_float(Fraction(10) ** 400) is None


def test_weeks_to_reach():
    assert calc.weeks_to_reach(P, M, Fraction(1000)) == 7      # 1,280 ≥ 1,000 > 640
    assert calc.weeks_to_reach(P, M, Fraction(1280)) == 7
    assert calc.weeks_to_reach(P, M, Fraction(5)) == 0


def test_progress_summary():
    actuals = {1: Fraction(20), 2: Fraction(30)}
    s = calc.progress_summary(P, M, actuals)
    assert s.weeks_completed == 2
    assert s.achievement_pct == 75
    assert s.total_growth_amount == 20
    assert s.weeks_ahead == pytest.approx(-0.415, abs=1e-3)   # log2(3) − 2
    assert calc.progress_summary(P, M, {}) is None


def test_database_roundtrip(tmp_path):
    db = TrackerDB(f"sqlite:///{tmp_path / 't.db'}")
    db.upsert_balance(1, Decimal("19.50"), "first")
    db.upsert_balance(1, Decimal("21.00"), "edited")
    db.upsert_balance(2, Decimal("41.25"))
    rows = db.list_balances()
    assert [(r["week"], r["actual_balance"], r["note"]) for r in rows] == [
        (1, Decimal("21.00"), "edited"), (2, Decimal("41.25"), "")]
    assert db.delete_balance(2) and not db.delete_balance(2)
    db.set_setting("multiplier", "2")
    db.set_setting("multiplier", "3")
    assert db.get_setting("multiplier") == "3"
    # A fresh connection to the same file sees the data (persistence).
    assert TrackerDB(f"sqlite:///{tmp_path / 't.db'}").get_balance(1)["note"] == "edited"
