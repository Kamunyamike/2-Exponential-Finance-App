"""Calculation engine for the USD Money Doubling Tracker.

This module holds all of the business logic and has no Streamlit imports, so it
can be unit-tested and reused on its own.

Money is held as ``fractions.Fraction`` values. Python integers have unlimited
precision, so ``P × mⁿ`` is computed exactly for any number of weeks (for the
default challenge it is pure integer arithmetic: 10 × 2ⁿ). Values are only
rounded to cents (half-up) when they are displayed or exported, and only
converted to ``float`` when they are sent to a chart.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Iterable, List, Mapping, Optional, Union

import pandas as pd

# ---------------------------------------------------------------------------
# Limits and defaults
# ---------------------------------------------------------------------------
DEFAULT_CAPITAL = Fraction(10)
DEFAULT_MULTIPLIER = Fraction(2)
DEFAULT_WEEK = 5

MIN_CAPITAL = Fraction(1, 100)            # $0.01
MAX_CAPITAL = Fraction(1_000_000_000)     # $1 billion
MIN_MULTIPLIER = Fraction(101, 100)       # 1.01× per week
MAX_MULTIPLIER = Fraction(10)             # 10× per week
MAX_WEEKS = 520                           # 10 years of weekly compounding
MAX_ACTUAL_BALANCE = Fraction(10) ** 30   # sanity cap on typed-in balances
MAX_INPUT_EXPONENT = 40                   # reject inputs like "1e999999" early

# Whole-dollar amounts with more digits than this are shown in scientific form
# (e.g. "$1.07 × 10^157") instead of a 150-digit string.
FULL_DIGIT_LIMIT = 21

Number = Union[int, float, str, Decimal, Fraction]


class ValidationError(ValueError):
    """Raised when an input is missing, malformed or outside the allowed range."""


# ---------------------------------------------------------------------------
# Parsing and validation
# ---------------------------------------------------------------------------
def to_fraction(value: Number) -> Fraction:
    """Convert a user-facing number into an exact Fraction.

    Accepts ints, floats, Decimals, Fractions and strings such as
    ``"$1,250.50"``. Floats are converted through their shortest decimal
    representation, so ``0.1`` becomes exactly 1/10.
    """
    if isinstance(value, bool) or value is None:
        raise ValidationError("Please enter a number.")
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value)

    if isinstance(value, Decimal):
        dec = value
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValidationError("Please enter a finite number.")
        dec = Decimal(repr(value))
    elif isinstance(value, str):
        cleaned = value.strip().upper().replace("USD", "")
        cleaned = cleaned.replace("$", "").replace(",", "").replace(" ", "")
        if not cleaned:
            raise ValidationError("Please enter an amount.")
        try:
            dec = Decimal(cleaned)
        except InvalidOperation:
            raise ValidationError(f"'{value.strip()}' is not a valid number.") from None
    else:
        raise ValidationError(f"Unsupported value type: {type(value).__name__}.")

    if not dec.is_finite():
        raise ValidationError("Please enter a finite number.")
    if dec != 0 and dec.adjusted() > MAX_INPUT_EXPONENT:
        raise ValidationError("That number is far too large.")
    return Fraction(dec)


def validate_capital(value: Number) -> Fraction:
    """Validate the initial capital and round it to whole cents."""
    amount = to_fraction(value)
    amount = Fraction(to_cents(amount), 100)
    if amount < MIN_CAPITAL:
        raise ValidationError("Initial capital must be at least $0.01.")
    if amount > MAX_CAPITAL:
        raise ValidationError(f"Initial capital cannot exceed {format_usd(MAX_CAPITAL)}.")
    return amount


def validate_multiplier(value: Number) -> Fraction:
    """Validate the weekly multiplication factor (rounded to 4 decimal places)."""
    factor = to_fraction(value)
    factor = Fraction(_round_half_up(factor, 10_000), 10_000)
    if factor < MIN_MULTIPLIER or factor > MAX_MULTIPLIER:
        raise ValidationError(
            f"The weekly multiplier must be between {float(MIN_MULTIPLIER):g} "
            f"and {float(MAX_MULTIPLIER):g}."
        )
    return factor


def validate_week(value: Union[int, float, str]) -> int:
    """Validate a week number: a whole number from 0 to MAX_WEEKS."""
    if isinstance(value, bool) or value is None:
        raise ValidationError("Please enter a week number.")
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise ValidationError("The week number must be a whole number.")
        value = int(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text.lstrip("-").isdigit():
            raise ValidationError("The week number must be a whole number.")
        value = int(text)
    elif not isinstance(value, int):
        raise ValidationError("The week number must be a whole number.")

    if value < 0:
        raise ValidationError("The week number cannot be negative.")
    if value > MAX_WEEKS:
        raise ValidationError(f"The week number cannot be greater than {MAX_WEEKS}.")
    return value


def validate_actual_balance(value: Number) -> Fraction:
    """Validate a recorded actual balance (zero or more, rounded to cents)."""
    amount = to_fraction(value)
    if amount < 0:
        raise ValidationError("A balance cannot be negative.")
    if amount > MAX_ACTUAL_BALANCE:
        raise ValidationError("That balance is unrealistically large.")
    return Fraction(to_cents(amount), 100)


# ---------------------------------------------------------------------------
# Core maths
# ---------------------------------------------------------------------------
def projected_balance(capital: Fraction, multiplier: Fraction, week: int) -> Fraction:
    """Aₙ = P × mⁿ, computed exactly."""
    week = validate_week(week)
    return capital * multiplier ** week


def growth_pct(capital: Fraction, amount: Fraction) -> Fraction:
    """Percentage increase of ``amount`` over ``capital``."""
    if capital == 0:
        raise ValidationError("Initial capital cannot be zero.")
    return (amount - capital) / capital * 100


def weeks_to_reach(capital: Fraction, multiplier: Fraction, target: Fraction) -> int:
    """Smallest whole number of weeks n with P × mⁿ ≥ target."""
    if target <= capital:
        return 0
    estimate = math.ceil(
        (log10_fraction(target) - log10_fraction(capital)) / log10_fraction(multiplier)
    )
    n = max(estimate, 0)
    # Correct any floating-point error in the estimate using exact arithmetic.
    while n > 0 and capital * multiplier ** (n - 1) >= target:
        n -= 1
    while capital * multiplier ** n < target:
        n += 1
    return n


def equivalent_week(capital: Fraction, multiplier: Fraction, balance: Fraction) -> Optional[float]:
    """The (fractional) week at which the projection equals ``balance``."""
    if balance <= 0:
        return None
    return (log10_fraction(balance) - log10_fraction(capital)) / log10_fraction(multiplier)


@dataclass(frozen=True)
class WeekSummary:
    week: int
    projected: Fraction
    previous: Optional[Fraction]
    weekly_gain: Fraction
    total_increase: Fraction
    growth_pct: Fraction


def week_summary(capital: Fraction, multiplier: Fraction, week: int) -> WeekSummary:
    week = validate_week(week)
    projected = projected_balance(capital, multiplier, week)
    previous = projected_balance(capital, multiplier, week - 1) if week > 0 else None
    return WeekSummary(
        week=week,
        projected=projected,
        previous=previous,
        weekly_gain=projected - previous if previous is not None else Fraction(0),
        total_increase=projected - capital,
        growth_pct=growth_pct(capital, projected),
    )


@dataclass(frozen=True)
class ScheduleRow:
    week: int
    opening: Optional[Fraction]   # None for week 0 (the starting capital)
    weekly_target: Fraction       # gain required during this week
    closing: Fraction
    growth_pct: Fraction          # cumulative growth vs. initial capital


def growth_schedule(capital: Fraction, multiplier: Fraction, weeks: int) -> List[ScheduleRow]:
    """Every week from the starting capital (week 0) through ``weeks``."""
    weeks = validate_week(weeks)
    rows = [ScheduleRow(0, None, Fraction(0), capital, Fraction(0))]
    balance = capital
    for week in range(1, weeks + 1):
        opening = balance
        closing = opening * multiplier
        rows.append(
            ScheduleRow(week, opening, closing - opening, closing, growth_pct(capital, closing))
        )
        balance = closing
    return rows


def projection_series(capital: Fraction, multiplier: Fraction, weeks: int) -> List[Fraction]:
    """Projected balance for weeks 0..weeks (exact values)."""
    weeks = validate_week(weeks)
    values = [capital]
    for _ in range(weeks):
        values.append(values[-1] * multiplier)
    return values


# ---------------------------------------------------------------------------
# Actual vs projected
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ComparisonRow:
    week: int
    projected: Fraction
    actual: Fraction
    difference: Fraction          # actual − projected
    achievement_pct: Fraction     # actual ÷ projected × 100
    note: str = ""


def compare_actuals(
    capital: Fraction,
    multiplier: Fraction,
    actuals: Mapping[int, Fraction],
    notes: Optional[Mapping[int, str]] = None,
) -> List[ComparisonRow]:
    notes = notes or {}
    rows = []
    for week in sorted(actuals):
        projected = projected_balance(capital, multiplier, week)
        actual = actuals[week]
        rows.append(
            ComparisonRow(
                week=week,
                projected=projected,
                actual=actual,
                difference=actual - projected,
                achievement_pct=actual / projected * 100,
                note=notes.get(week, ""),
            )
        )
    return rows


@dataclass(frozen=True)
class ProgressSummary:
    entries: int
    weeks_completed: int
    latest_actual: Fraction
    latest_projected: Fraction
    achievement_pct: Fraction
    total_growth_amount: Fraction
    total_growth_pct: Fraction
    equivalent_week: Optional[float]
    weeks_ahead: Optional[float]   # positive = ahead of schedule


def progress_summary(
    capital: Fraction, multiplier: Fraction, actuals: Mapping[int, Fraction]
) -> Optional[ProgressSummary]:
    if not actuals:
        return None
    latest_week = max(actuals)
    latest_actual = actuals[latest_week]
    latest_projected = projected_balance(capital, multiplier, latest_week)
    eq_week = equivalent_week(capital, multiplier, latest_actual)
    return ProgressSummary(
        entries=len(actuals),
        weeks_completed=latest_week,
        latest_actual=latest_actual,
        latest_projected=latest_projected,
        achievement_pct=latest_actual / latest_projected * 100,
        total_growth_amount=latest_actual - capital,
        total_growth_pct=growth_pct(capital, latest_actual),
        equivalent_week=eq_week,
        weeks_ahead=None if eq_week is None else eq_week - latest_week,
    )


def describe_pace(weeks_ahead: Optional[float]) -> str:
    if weeks_ahead is None:
        return "No balance yet"
    if abs(weeks_ahead) < 0.005:
        return "Exactly on target"
    direction = "ahead" if weeks_ahead > 0 else "behind"
    return f"{abs(weeks_ahead):,.2f} weeks {direction}"


# ---------------------------------------------------------------------------
# Rounding and formatting
# ---------------------------------------------------------------------------
def _round_half_up(value: Fraction, scale: int) -> int:
    """Round ``value × scale`` to the nearest integer, halves away from zero."""
    scaled = Fraction(value) * scale
    sign = -1 if scaled < 0 else 1
    quotient, remainder = divmod(abs(scaled.numerator), scaled.denominator)
    if 2 * remainder >= scaled.denominator:
        quotient += 1
    return sign * quotient


def to_cents(value: Fraction) -> int:
    return _round_half_up(value, 100)


def _scientific(n: int) -> str:
    """Format a large positive integer as '1.23 × 10^45'."""
    exponent = len(str(n)) - 1
    mantissa = _round_half_up(Fraction(n, 10 ** (exponent - 2)), 1)  # 3 significant digits
    if mantissa >= 1000:
        mantissa //= 10
        exponent += 1
    return f"{mantissa // 100}.{mantissa % 100:02d} × 10^{exponent}"


_COMPACT_UNITS = (
    (10 ** 18, "Qi"),
    (10 ** 15, "Qa"),
    (10 ** 12, "T"),
    (10 ** 9, "B"),
    (10 ** 6, "M"),
)


def format_usd(value: Number, *, compact: bool = False, signed: bool = False) -> str:
    """Format as USD with thousands separators and two decimals.

    ``compact=True`` abbreviates amounts of $1 million or more ("$1.07B").
    Amounts with more than FULL_DIGIT_LIMIT whole-dollar digits always use
    scientific notation so the UI stays readable.
    """
    cents = to_cents(to_fraction(value))
    if cents < 0:
        sign = "-"
    elif signed and cents > 0:
        sign = "+"
    else:
        sign = ""
    dollars, rem = divmod(abs(cents), 100)

    if compact and dollars >= 10 ** 6:
        if dollars >= 10 ** 21:
            return f"{sign}${_scientific(dollars)}"
        for threshold, suffix in _COMPACT_UNITS:
            if dollars >= threshold:
                hundredths = _round_half_up(Fraction(abs(cents), 100 * threshold), 100)
                return f"{sign}${hundredths // 100:,}.{hundredths % 100:02d}{suffix}"
    if len(str(dollars)) > FULL_DIGIT_LIMIT:
        return f"{sign}${_scientific(dollars)}"
    return f"{sign}${dollars:,}.{rem:02d}"


def format_pct(value: Number, *, signed: bool = False) -> str:
    hundredths = _round_half_up(to_fraction(value), 100)
    sign = "-" if hundredths < 0 else ("+" if signed and hundredths > 0 else "")
    whole, rem = divmod(abs(hundredths), 100)
    if len(str(whole)) > FULL_DIGIT_LIMIT:
        return f"{sign}{_scientific(whole)}%"
    return f"{sign}{whole:,}.{rem:02d}%"


def format_multiplier(value: Fraction) -> str:
    text = f"{float(value):.4f}".rstrip("0").rstrip(".")
    return f"{text}×"


def to_plain_decimal(value: Fraction) -> str:
    """Exact value rounded to cents, without currency symbol or separators (for CSV)."""
    cents = to_cents(value)
    sign = "-" if cents < 0 else ""
    dollars, rem = divmod(abs(cents), 100)
    return f"{sign}{dollars}.{rem:02d}"


def digit_count(value: Fraction) -> int:
    """Number of whole-dollar digits in ``value``."""
    return len(str(abs(to_cents(value)) // 100))


def safe_float(value: Fraction) -> Optional[float]:
    """Convert to float for charting; None if the value is beyond float range."""
    try:
        result = float(value)
    except OverflowError:
        return None
    return result if math.isfinite(result) else None


def log10_fraction(value: Fraction) -> float:
    """log10 of a positive Fraction; works for integers of any size."""
    value = Fraction(value)
    if value <= 0:
        raise ValidationError("Logarithm is only defined for positive values.")
    return math.log10(value.numerator) - math.log10(value.denominator)


# ---------------------------------------------------------------------------
# Tabular output
# ---------------------------------------------------------------------------
def schedule_dataframe(rows: Iterable[ScheduleRow], *, for_export: bool = False) -> pd.DataFrame:
    rows = list(rows)
    if for_export:
        return pd.DataFrame(
            {
                "Week": [r.week for r in rows],
                "Opening Balance (USD)": [
                    "" if r.opening is None else to_plain_decimal(r.opening) for r in rows
                ],
                "Weekly Target (USD)": [to_plain_decimal(r.weekly_target) for r in rows],
                "Closing Balance (USD)": [to_plain_decimal(r.closing) for r in rows],
                "Growth (%)": [to_plain_decimal(r.growth_pct) for r in rows],
            }
        )
    return pd.DataFrame(
        {
            "Week": [("Start" if r.week == 0 else str(r.week)) for r in rows],
            "Opening Balance": ["—" if r.opening is None else format_usd(r.opening) for r in rows],
            "Weekly Target": [
                "—" if r.week == 0 else format_usd(r.weekly_target, signed=True) for r in rows
            ],
            "Closing Balance": [format_usd(r.closing) for r in rows],
            "Growth": [format_pct(r.growth_pct) for r in rows],
        }
    )


def comparison_dataframe(rows: Iterable[ComparisonRow], *, for_export: bool = False) -> pd.DataFrame:
    rows = list(rows)
    if for_export:
        return pd.DataFrame(
            {
                "Week": [r.week for r in rows],
                "Projected Balance (USD)": [to_plain_decimal(r.projected) for r in rows],
                "Actual Balance (USD)": [to_plain_decimal(r.actual) for r in rows],
                "Difference (USD)": [to_plain_decimal(r.difference) for r in rows],
                "Achievement (%)": [to_plain_decimal(r.achievement_pct) for r in rows],
                "Note": [r.note for r in rows],
            }
        )
    return pd.DataFrame(
        {
            "Week": [r.week for r in rows],
            "Projected": [format_usd(r.projected) for r in rows],
            "Actual": [format_usd(r.actual) for r in rows],
            "Difference": [format_usd(r.difference, signed=True) for r in rows],
            "Achievement": [format_pct(r.achievement_pct) for r in rows],
            "Note": [r.note for r in rows],
        }
    )
