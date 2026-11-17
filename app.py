"""Two Power Exponent — Streamlit front end.

Run locally with:  streamlit run app.py

All maths lives in calculations.py and all storage in database.py; this file
only handles layout, user input and charts.
"""

from __future__ import annotations

import html
import io
from decimal import Decimal
from fractions import Fraction
from typing import Dict, List, Optional, Tuple

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import calculations as calc
from database import DatabaseError, TrackerDB

st.set_page_config(
    page_title="Exponent growth",
    page_icon="dash.png",
    layout="wide",
    initial_sidebar_state="auto",
)

# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------
NAVY = "#0B1426"
CARD = "#111D35"
BORDER = "#1F3155"
TEXT = "#F1F5F9"
MUTED = "#94A3B8"
GREEN = "#34D399"
BLUE = "#60A5FA"
AMBER = "#FBBF24"
RED = "#F87171"
GRID = "rgba(148,163,184,0.12)"

CSS = f"""
<style>
.stApp {{
    background: radial-gradient(1200px 600px at 15% -10%, #142A4D 0%, {NAVY} 55%) fixed;
}}
[data-testid="stSidebar"] {{ background: #0D182D; border-right: 1px solid {BORDER}; }}
.block-container {{ padding-top: 3.6rem; padding-bottom: 3rem; max-width: 1280px; }}
#MainMenu, footer {{ visibility: hidden; }}

.hero {{ display:flex; justify-content:space-between; align-items:flex-end; flex-wrap:wrap;
         gap: .75rem; margin-bottom: 1.25rem; }}
.hero h1 {{ font-size: 1.85rem; font-weight: 700; letter-spacing: -0.02em; margin: 0; padding: 0;
            color: {TEXT}; }}
.hero p {{ color: {MUTED}; margin: .3rem 0 0; font-size: .95rem; }}
.formula {{ background: rgba(52,211,153,.08); border: 1px solid rgba(52,211,153,.25);
            color: {GREEN}; border-radius: 10px; padding: 8px 14px; font-family: ui-monospace,
            SFMono-Regular, Menlo, monospace; font-size: .9rem; white-space: nowrap; }}

.kpi-card {{ background: linear-gradient(180deg, #15233F 0%, {CARD} 100%);
             border: 1px solid {BORDER}; border-radius: 14px; padding: 18px 20px 16px 22px;
             min-height: 128px; position: relative; overflow: hidden;
             box-shadow: 0 10px 28px rgba(0,0,0,.25); margin-bottom: .6rem; }}
.kpi-card::before {{ content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px;
                     background: var(--accent, {GREEN}); }}
.kpi-label {{ font-size: .74rem; text-transform: uppercase; letter-spacing: .09em; color: {MUTED};
              font-weight: 600; }}
.kpi-value {{ font-size: 1.6rem; font-weight: 700; color: #F8FAFC; margin-top: 8px; line-height: 1.2;
              font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }}
.kpi-sub {{ font-size: .82rem; color: {MUTED}; margin-top: 6px; }}
.kpi-sub.up {{ color: {GREEN}; }}
.kpi-sub.down {{ color: {RED}; }}

.section-title {{ font-size: 1.05rem; font-weight: 650; color: #E2E8F0; margin: 1.6rem 0 .7rem; }}
.panel {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 14px; padding: 6px 20px; }}
.stat-row {{ display: flex; justify-content: space-between; gap: 1rem; padding: 11px 0;
             border-bottom: 1px solid {BORDER}; }}
.stat-row:last-child {{ border-bottom: none; }}
.stat-row .k {{ color: {MUTED}; }}
.stat-row .v {{ font-weight: 600; color: {TEXT}; text-align: right; font-variant-numeric: tabular-nums;
                overflow-wrap: anywhere; }}
.stat-row .v.up {{ color: {GREEN}; }}
.pill {{ display: inline-block; padding: 3px 11px; border-radius: 999px; font-size: .78rem;
         font-weight: 600; }}
.pill.green {{ background: rgba(52,211,153,.14); color: {GREEN}; }}
.pill.amber {{ background: rgba(251,191,36,.14); color: {AMBER}; }}
.pill.red {{ background: rgba(248,113,113,.14); color: {RED}; }}
.brand {{ font-weight: 700; font-size: 1.15rem; color: {TEXT}; margin-bottom: .1rem; }}
.brand span {{ color: {GREEN}; }}
.muted {{ color: {MUTED}; font-size: .85rem; }}
.stDownloadButton button, .stButton button {{ border-radius: 10px; }}

@media (max-width: 640px) {{
    .block-container {{ padding-top: 3.2rem; padding-left: .8rem; padding-right: .8rem; }}
    .hero h1 {{ font-size: 1.4rem; }}
    .kpi-value {{ font-size: 1.3rem; }}
    .kpi-card {{ min-height: 0; }}
    .formula {{ white-space: normal; }}
}}
</style>
"""

PAGES = {
    "dashboard": "📊  Dashboard",
    "calculator": "🧮  Week Calculator",
    "table": "📋  Growth Table",
    "chart": "📈  Growth Chart",
    "tracking": "✍️  Actual Tracking",
    "progress": "🎯  Progress",
}

MILESTONES = [Fraction(1_000), Fraction(1_000_000), Fraction(1_000_000_000)]


# ---------------------------------------------------------------------------
# Database & state
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def get_database() -> TrackerDB:
    return TrackerDB()


def init_state(db: TrackerDB) -> None:
    if st.session_state.get("_initialised"):
        return
    try:
        capital = calc.validate_capital(db.get_setting("initial_capital", "10"))
        multiplier = calc.validate_multiplier(db.get_setting("multiplier", "2"))
        week = calc.validate_week(db.get_setting("selected_week", str(calc.DEFAULT_WEEK)))
    except (calc.ValidationError, DatabaseError):
        capital, multiplier, week = calc.DEFAULT_CAPITAL, calc.DEFAULT_MULTIPLIER, calc.DEFAULT_WEEK
    st.session_state.capital = float(capital)
    st.session_state.multiplier = float(multiplier)
    st.session_state.week = int(week)
    st.session_state.page = "dashboard"
    st.session_state._initialised = True


def _save_setting(key: str, value) -> None:
    try:
        get_database().set_setting(key, str(value))
    except DatabaseError:
        pass  # settings are a convenience; the app keeps working without them


def on_settings_change() -> None:
    _save_setting("initial_capital", st.session_state.capital)
    _save_setting("multiplier", st.session_state.multiplier)


def on_week_change(source_key: str) -> None:
    st.session_state.week = int(st.session_state[source_key])
    _save_setting("selected_week", st.session_state.week)


def reset_defaults() -> None:
    st.session_state.capital = float(calc.DEFAULT_CAPITAL)
    st.session_state.multiplier = float(calc.DEFAULT_MULTIPLIER)
    st.session_state.week = calc.DEFAULT_WEEK
    on_settings_change()
    _save_setting("selected_week", calc.DEFAULT_WEEK)


def go_to(page: str) -> None:
    st.session_state.page = page


def flash(kind: str, message: str) -> None:
    st.session_state._flash = (kind, message)


def show_flash() -> None:
    item = st.session_state.pop("_flash", None)
    if item:
        kind, message = item
        getattr(st, kind)(message)


def load_actuals(db: TrackerDB) -> Tuple[Dict[int, Fraction], Dict[int, str], List[Dict]]:
    records = db.list_balances()
    actuals, notes = {}, {}
    for r in records:
        if 0 <= r["week"] <= calc.MAX_WEEKS:
            actuals[r["week"]] = Fraction(r["actual_balance"])
            notes[r["week"]] = r["note"]
    return actuals, notes, records


# ---------------------------------------------------------------------------
# UI components
# ---------------------------------------------------------------------------
def esc(text) -> str:
    return html.escape(str(text))


def kpi_card(label: str, value: str, sub: str = "", accent: str = GREEN, tone: str = "") -> None:
    st.markdown(
        f"""<div class="kpi-card" style="--accent:{accent}">
              <div class="kpi-label">{esc(label)}</div>
              <div class="kpi-value">{esc(value)}</div>
              <div class="kpi-sub {tone}">{esc(sub)}</div>
            </div>""",
        unsafe_allow_html=True,
    )


def stat_panel(rows: List[Tuple[str, str, str]]) -> None:
    """rows = [(label, value, css_class)]"""
    body = "".join(
        f'<div class="stat-row"><span class="k">{esc(k)}</span>'
        f'<span class="v {cls}">{esc(v)}</span></div>'
        for k, v, cls in rows
    )
    st.markdown(f'<div class="panel">{body}</div>', unsafe_allow_html=True)


def section(title: str) -> None:
    st.markdown(f'<div class="section-title">{esc(title)}</div>', unsafe_allow_html=True)


def hero(title: str, subtitle: str, capital: Fraction, multiplier: Fraction) -> None:
    formula = f"Aₙ = {calc.format_usd(capital)} × {calc.format_multiplier(multiplier).rstrip('×')}ⁿ"
    st.markdown(
        f"""<div class="hero">
              <div><h1>{esc(title)}</h1><p>{esc(subtitle)}</p></div>
              <div class="formula">{esc(formula)}</div>
            </div>""",
        unsafe_allow_html=True,
    )


def pace_pill(weeks_ahead: Optional[float]) -> str:
    text = calc.describe_pace(weeks_ahead)
    if weeks_ahead is None:
        cls = "amber"
    elif weeks_ahead >= -0.005:
        cls = "green"
    elif weeks_ahead > -1:
        cls = "amber"
    else:
        cls = "red"
    return f'<span class="pill {cls}">{esc(text)}</span>'


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------
def _base_layout(fig: go.Figure, *, log_y: bool, max_y: float, height: int = 430) -> go.Figure:
    yaxis = dict(
        title="Balance (USD)",
        type="log" if log_y else "linear",
        gridcolor=GRID,
        zeroline=False,
        tickprefix="$",
    )
    if max_y >= 1e9:
        yaxis.update(exponentformat="power", showexponent="all")
    else:
        yaxis.update(tickformat=",.0f" if max_y >= 100 else ",.2f")
    if not log_y:
        yaxis["rangemode"] = "tozero"

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=TEXT, family="Inter, system-ui, sans-serif"),
        height=height,
        margin=dict(l=10, r=10, t=30, b=10),
        hovermode="closest",
        hoverlabel=dict(bgcolor="#0F1B31", bordercolor=BORDER, font=dict(color=TEXT)),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                    bgcolor="rgba(0,0,0,0)"),
        xaxis=dict(title="Week", gridcolor=GRID, zeroline=False, rangemode="tozero"),
        yaxis=yaxis,
    )
    return fig


def growth_figure(
    capital: Fraction, multiplier: Fraction, selected: int, horizon: int, log_y: bool
) -> Tuple[go.Figure, int]:
    values = calc.projection_series(capital, multiplier, horizon)
    xs, ys, labels = [], [], []
    omitted = 0
    for week, value in enumerate(values):
        as_float = calc.safe_float(value)
        if as_float is None:
            omitted += 1
            continue
        xs.append(week)
        ys.append(as_float)
        labels.append(calc.format_usd(value, compact=True))

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=xs, y=ys, customdata=labels, name="Projected balance",
            mode="lines+markers" if len(xs) <= 60 else "lines",
            line=dict(color=GREEN, width=3),
            marker=dict(size=6, color=GREEN),
            fill=None if log_y else "tozeroy",
            fillcolor="rgba(52,211,153,0.08)",
            hovertemplate="<b>Week %{x}</b><br>Projected: %{customdata}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[0], y=[float(capital)], name="Starting capital",
            mode="markers+text", text=[f"Start {calc.format_usd(capital)}"],
            textposition="top right", textfont=dict(color=BLUE),
            marker=dict(size=13, color=BLUE, line=dict(color=NAVY, width=2)),
            hovertemplate=f"<b>Starting capital</b><br>{calc.format_usd(capital)}<extra></extra>",
        )
    )
    if selected in xs and selected != 0:
        idx = xs.index(selected)
        fig.add_trace(
            go.Scatter(
                x=[selected], y=[ys[idx]], name=f"Week {selected}",
                mode="markers+text", text=[labels[idx]], textposition="top left",
                textfont=dict(color=AMBER),
                marker=dict(size=17, color=AMBER, symbol="star", line=dict(color=NAVY, width=1)),
                hovertemplate=f"<b>Selected: week {selected}</b><br>{labels[idx]}<extra></extra>",
            )
        )
        fig.add_vline(x=selected, line=dict(color=AMBER, width=1, dash="dot"))
    _base_layout(fig, log_y=log_y, max_y=max(ys) if ys else 0)
    return fig, omitted


def progress_figure(
    capital: Fraction, multiplier: Fraction, actuals: Dict[int, Fraction], horizon: int, log_y: bool
) -> go.Figure:
    projected = calc.projection_series(capital, multiplier, horizon)
    px, py, plab = [], [], []
    for week, value in enumerate(projected):
        f = calc.safe_float(value)
        if f is not None:
            px.append(week)
            py.append(f)
            plab.append(calc.format_usd(value, compact=True))

    ax, ay, alab = [], [], []
    for week in sorted(actuals):
        f = calc.safe_float(actuals[week])
        if f is None or (log_y and f <= 0):
            continue
        proj = calc.projected_balance(capital, multiplier, week)
        ax.append(week)
        ay.append(f)
        alab.append(
            f"{calc.format_usd(actuals[week], compact=True)} "
            f"({calc.format_pct(actuals[week] / proj * 100)} of target)"
        )

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=px, y=py, customdata=plab, name="Projected",
            mode="lines", line=dict(color=GREEN, width=2, dash="dash"),
            hovertemplate="<b>Week %{x}</b><br>Projected: %{customdata}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=ax, y=ay, customdata=alab, name="Actual",
            mode="lines+markers", line=dict(color=BLUE, width=3),
            marker=dict(size=9, color=BLUE, line=dict(color=NAVY, width=2)),
            hovertemplate="<b>Week %{x}</b><br>Actual: %{customdata}<extra></extra>",
        )
    )
    _base_layout(fig, log_y=log_y, max_y=max(py + ay) if (py or ay) else 0)
    return fig


def achievement_figure(rows: List[calc.ComparisonRow]) -> go.Figure:
    weeks = [r.week for r in rows]
    pct = [float(r.achievement_pct) for r in rows]
    colors = [GREEN if p >= 100 else (AMBER if p >= 75 else RED) for p in pct]
    fig = go.Figure(
        go.Bar(
            x=weeks, y=pct, marker_color=colors, name="Achievement",
            customdata=[calc.format_pct(r.achievement_pct) for r in rows],
            hovertemplate="<b>Week %{x}</b><br>Achievement: %{customdata}<extra></extra>",
        )
    )
    fig.add_hline(y=100, line=dict(color=MUTED, width=1, dash="dot"),
                  annotation_text="Target 100%", annotation_font_color=MUTED)
    fig.update_layout(
        template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=TEXT), height=300, margin=dict(l=10, r=10, t=20, b=10),
        xaxis=dict(title="Week", gridcolor=GRID, dtick=1 if len(weeks) <= 20 else None),
        yaxis=dict(title="% of weekly target", gridcolor=GRID, ticksuffix="%", rangemode="tozero"),
        showlegend=False,
    )
    return fig


CHART_CONFIG = {"displayModeBar": False, "responsive": True}


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
def page_dashboard(capital: Fraction, multiplier: Fraction, week: int, db: TrackerDB) -> None:
    hero("Dashboard", "Your weekly compounding challenge at a glance.", capital, multiplier)
    s = calc.week_summary(capital, multiplier, week)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        kpi_card("Initial capital", calc.format_usd(capital), "Starting point (week 0)", BLUE)
    with c2:
        kpi_card("Current week", f"Week {week}",
                 f"{calc.format_multiplier(multiplier)} growth per week", AMBER)
    with c3:
        sub = f"{calc.format_usd(s.weekly_gain, compact=True, signed=True)} this week" if week else "No growth yet"
        kpi_card("Projected balance", calc.format_usd(s.projected, compact=True), sub, GREEN,
                 "up" if week else "")
    with c4:
        kpi_card("Total growth", calc.format_pct(s.growth_pct),
                 f"{calc.format_usd(s.total_increase, compact=True, signed=True)} vs initial", GREEN,
                 "up" if week else "")

    left, right = st.columns([2, 1])
    with left:
        section("Growth curve")
        horizon = max(week, 10)
        fig, _ = growth_figure(capital, multiplier, week, horizon, log_y=horizon > 20)
        st.plotly_chart(fig, config=CHART_CONFIG, width="stretch")
    with right:
        section("Milestones")
        rows = []
        for target in MILESTONES:
            n = calc.weeks_to_reach(capital, multiplier, target)
            status = "✓ reached" if n <= week else f"in {n - week} more"
            rows.append((f"{calc.format_usd(target, compact=True).replace('.00', '')} target",
                         f"Week {n} · {status}", "up" if n <= week else ""))
        stat_panel(rows)

        section("Your actual progress")
        try:
            actuals, _, _ = load_actuals(db)
        except DatabaseError as exc:
            st.warning(f"Could not load recorded balances: {exc}")
            actuals = {}
        summary = calc.progress_summary(capital, multiplier, actuals)
        if summary is None:
            st.markdown('<div class="muted">No actual balances recorded yet.</div>',
                        unsafe_allow_html=True)
            st.button("Record your first week →", on_click=go_to, args=("tracking",))
        else:
            stat_panel([
                ("Latest recorded week", f"Week {summary.weeks_completed}", ""),
                ("Actual balance", calc.format_usd(summary.latest_actual, compact=True), ""),
                ("Achievement", calc.format_pct(summary.achievement_pct),
                 "up" if summary.achievement_pct >= 100 else ""),
            ])
            st.markdown(pace_pill(summary.weeks_ahead), unsafe_allow_html=True)


def page_calculator(capital: Fraction, multiplier: Fraction) -> None:
    hero("Week Calculator", "Enter any week to see exactly where the challenge puts you.",
         capital, multiplier)
    st.session_state.week_calc = st.session_state.week
    st.number_input(
        "Number of completed weeks",
        min_value=0, max_value=calc.MAX_WEEKS, step=1, key="week_calc",
        on_change=on_week_change, args=("week_calc",),
        help=f"Any whole number from 0 to {calc.MAX_WEEKS}. Week 0 is your starting capital.",
    )
    week = int(st.session_state.week)
    s = calc.week_summary(capital, multiplier, week)

    c1, c2, c3 = st.columns(3)
    with c1:
        kpi_card("Projected amount", calc.format_usd(s.projected, compact=True), f"End of week {week}")
    with c2:
        kpi_card("Total increase", calc.format_usd(s.total_increase, compact=True, signed=True),
                 "Since initial capital", BLUE)
    with c3:
        kpi_card("Percentage growth", calc.format_pct(s.growth_pct), "vs initial capital", AMBER)

    section("Breakdown")
    stat_panel([
        ("Week number", str(week), ""),
        ("Projected amount", calc.format_usd(s.projected), ""),
        ("Previous week's amount", "—" if s.previous is None else calc.format_usd(s.previous), ""),
        ("Required gain this week", "—" if week == 0 else calc.format_usd(s.weekly_gain, signed=True), "up"),
        ("Total increase from initial capital", calc.format_usd(s.total_increase, signed=True), "up"),
        ("Percentage growth", calc.format_pct(s.growth_pct), "up"),
    ])
    st.caption(
        f"Formula: {calc.format_usd(capital)} × {calc.format_multiplier(multiplier).rstrip('×')}"
        f"^{week} = {calc.format_usd(s.projected)}"
    )
    digits = calc.digit_count(s.projected)
    if digits > calc.FULL_DIGIT_LIMIT:
        with st.expander(f"Show the exact value ({digits:,} digits)"):
            st.code(f"${calc.to_plain_decimal(s.projected)}", language=None, wrap_lines=True)


def page_table(capital: Fraction, multiplier: Fraction, week: int) -> None:
    hero("Weekly Growth Table", f"Every week from your starting capital to week {week}.",
         capital, multiplier)
    rows = calc.growth_schedule(capital, multiplier, week)
    st.dataframe(
        calc.schedule_dataframe(rows), hide_index=True, width="stretch",
        height=min(38 + 35 * len(rows), 620),
    )
    st.caption("Weekly Target = the gain needed during that week. "
               "Growth = cumulative increase over your initial capital.")
    csv = calc.schedule_dataframe(rows, for_export=True).to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇️  Download table as CSV", csv, file_name=f"money_doubling_weeks_0-{week}.csv",
        mime="text/csv", type="primary",
    )


def page_chart(capital: Fraction, multiplier: Fraction, week: int) -> None:
    hero("Growth Visualization", "Exponential growth of your initial capital.", capital, multiplier)
    c1, c2 = st.columns([3, 1])
    with c1:
        lower = max(week, 1)
        if lower >= calc.MAX_WEEKS:
            horizon = calc.MAX_WEEKS
            st.caption(f"Showing all {calc.MAX_WEEKS} weeks.")
        else:
            horizon = st.slider("Weeks shown", min_value=lower, max_value=calc.MAX_WEEKS,
                                value=max(lower, min(calc.MAX_WEEKS, max(week + 4, 12))))
    with c2:
        st.write("")
        log_y = st.toggle("Log scale", value=horizon > 20,
                          help="A log scale turns exponential growth into a straight line, "
                               "so early weeks stay visible.")
    fig, omitted = growth_figure(capital, multiplier, week, horizon, log_y)
    st.plotly_chart(fig, config=CHART_CONFIG, width="stretch")
    if omitted:
        st.info(f"{omitted} week(s) exceed the largest number a chart can draw (~1.8 × 10^308) "
                "and are left off. Their exact values are in the Growth Table.")
    st.caption("Blue dot = starting capital · Amber star = selected week (change it in the sidebar).")


def _prefill_tracking() -> None:
    try:
        record = get_database().get_balance(int(st.session_state.track_week))
    except DatabaseError:
        record = None
    st.session_state.track_amount = "" if record is None else f"{record['actual_balance']:,.2f}"
    st.session_state.track_note = "" if record is None else record["note"]


def page_tracking(capital: Fraction, multiplier: Fraction, db: TrackerDB) -> None:
    hero("Actual Performance Tracking", "Record your real balance at the end of each week.",
         capital, multiplier)
    show_flash()
    actuals, notes, records = load_actuals(db)

    if "track_week" not in st.session_state:
        st.session_state.track_week = min((max(actuals) + 1) if actuals else 1, calc.MAX_WEEKS)
        _prefill_tracking()
    elif "track_amount" not in st.session_state:
        _prefill_tracking()

    left, right = st.columns([1, 1.6])
    with left:
        section("Record or edit a week")
        st.number_input("Week", min_value=1, max_value=calc.MAX_WEEKS, step=1, key="track_week",
                        on_change=_prefill_tracking)
        tw = int(st.session_state.track_week)
        existing = tw in actuals
        st.text_input("Actual balance at end of week (USD)", key="track_amount",
                      placeholder="e.g. 18.50")
        st.text_input("Note (optional)", key="track_note", max_chars=500,
                      placeholder="e.g. Sold 2 items at the market")

        projected = calc.projected_balance(capital, multiplier, tw)
        preview = [("Projected for this week", calc.format_usd(projected), "")]
        raw = st.session_state.track_amount.strip()
        if raw:
            try:
                amount = calc.validate_actual_balance(raw)
                diff = amount - projected
                preview += [
                    ("Difference", calc.format_usd(diff, signed=True), "up" if diff >= 0 else ""),
                    ("Achievement", calc.format_pct(amount / projected * 100), ""),
                ]
            except calc.ValidationError as exc:
                st.error(str(exc))
        stat_panel(preview)
        st.write("")

        b1, b2 = st.columns(2)
        with b1:
            if st.button("Update week" if existing else "Save week", type="primary", width="stretch"):
                try:
                    amount = calc.validate_actual_balance(st.session_state.track_amount)
                    db.upsert_balance(tw, Decimal(calc.to_plain_decimal(amount)),
                                      st.session_state.track_note)
                    flash("success", f"Week {tw} saved: {calc.format_usd(amount)}")
                    st.session_state.pop("track_week", None)
                    st.session_state.pop("track_amount", None)
                    st.rerun()
                except calc.ValidationError as exc:
                    st.error(str(exc))
                except DatabaseError as exc:
                    st.error(f"Could not save: {exc}")
        with b2:
            if existing and st.button("Delete week", width="stretch"):
                try:
                    db.delete_balance(tw)
                    flash("info", f"Week {tw} deleted.")
                    st.session_state.pop("track_amount", None)
                    st.rerun()
                except DatabaseError as exc:
                    st.error(f"Could not delete: {exc}")
        if existing:
            st.caption(f"Week {tw} already has a recorded balance — saving will update it.")

    with right:
        section("Projected vs actual")
        if not actuals:
            st.info("No balances recorded yet. Enter your first week on the left.")
        else:
            rows = calc.compare_actuals(capital, multiplier, actuals, notes)
            st.dataframe(calc.comparison_dataframe(rows), hide_index=True, width="stretch",
                         height=min(38 + 35 * len(rows), 460))
            csv = calc.comparison_dataframe(rows, for_export=True).to_csv(index=False).encode("utf-8")
            st.download_button("⬇️  Download comparison CSV", csv,
                               file_name="actual_vs_projected.csv", mime="text/csv")

        with st.expander("💾  Backup, restore & storage"):
            st.markdown(f"**Storage in use:** {db.description}")
            if db.is_sqlite:
                st.caption("On Streamlit Community Cloud this file is erased when the app restarts. "
                           "Download a backup regularly, or set DATABASE_URL to a free hosted "
                           "PostgreSQL database for permanent storage (see README).")
            backup = pd.DataFrame(
                [{"week": r["week"], "actual_balance": format(r["actual_balance"], "f"),
                  "note": r["note"], "updated_at": r["updated_at"]} for r in records],
                columns=["week", "actual_balance", "note", "updated_at"],
            )
            st.download_button("Download backup CSV", backup.to_csv(index=False).encode("utf-8"),
                               file_name="money_tracker_backup.csv", mime="text/csv",
                               disabled=not records)
            upload = st.file_uploader("Restore from backup CSV", type=["csv"],
                                      help="Needs 'week' and 'actual_balance' columns. "
                                           "Existing weeks are overwritten.")
            if upload is not None and st.button("Import backup"):
                import_backup(upload, db)
            st.divider()
            confirm = st.checkbox("I understand this deletes every recorded balance")
            if st.button("Delete all recorded balances", disabled=not confirm or not records):
                try:
                    n = db.clear_balances()
                    flash("info", f"Deleted {n} recorded week(s).")
                    st.session_state.pop("track_week", None)
                    st.session_state.pop("track_amount", None)
                    st.rerun()
                except DatabaseError as exc:
                    st.error(str(exc))


def import_backup(upload, db: TrackerDB) -> None:
    try:
        df = pd.read_csv(io.BytesIO(upload.getvalue()), dtype=str, keep_default_na=False)
    except Exception as exc:  # malformed file
        st.error(f"Could not read that CSV: {exc}")
        return
    cols = {c.strip().lower().replace(" ", "_"): c for c in df.columns}
    week_col = cols.get("week")
    bal_col = cols.get("actual_balance") or cols.get("actual_balance_(usd)") or cols.get("actual")
    note_col = cols.get("note")
    if not week_col or not bal_col:
        st.error("The CSV needs 'week' and 'actual_balance' columns.")
        return
    records, errors = [], []
    for i, row in df.iterrows():
        try:
            w = calc.validate_week(row[week_col])
            if w == 0:
                raise calc.ValidationError("week 0 is the starting capital")
            amount = calc.validate_actual_balance(row[bal_col])
            records.append((w, Decimal(calc.to_plain_decimal(amount)),
                            row[note_col] if note_col else ""))
        except calc.ValidationError as exc:
            errors.append(f"Row {i + 2}: {exc}")
    if errors:
        st.error("Nothing was imported. Fix these rows first:\n\n" + "\n".join(errors[:10]))
        return
    try:
        n = db.import_balances(records)
    except DatabaseError as exc:
        st.error(str(exc))
        return
    flash("success", f"Imported {n} week(s) from backup.")
    st.session_state.pop("track_week", None)
    st.session_state.pop("track_amount", None)
    st.rerun()


def page_progress(capital: Fraction, multiplier: Fraction, week: int, db: TrackerDB) -> None:
    hero("Progress Monitoring", "How your real results compare with the plan.", capital, multiplier)
    actuals, notes, _ = load_actuals(db)
    summary = calc.progress_summary(capital, multiplier, actuals)
    if summary is None:
        st.info("Record at least one weekly balance to see your progress.")
        st.button("Go to Actual Tracking →", on_click=go_to, args=("tracking",), type="primary")
        return

    ach = summary.achievement_pct
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        kpi_card("Current achievement", calc.format_pct(ach),
                 f"of week {summary.weeks_completed} target",
                 GREEN if ach >= 100 else (AMBER if ach >= 75 else RED),
                 "up" if ach >= 100 else "down")
    with c2:
        kpi_card("Weeks completed", str(summary.weeks_completed),
                 f"{summary.entries} week(s) recorded", BLUE)
    with c3:
        kpi_card("Total capital growth", calc.format_usd(summary.total_growth_amount, compact=True, signed=True),
                 calc.format_pct(summary.total_growth_pct, signed=True) + " vs initial",
                 GREEN if summary.total_growth_amount >= 0 else RED,
                 "up" if summary.total_growth_amount >= 0 else "down")
    with c4:
        wa = summary.weeks_ahead
        kpi_card("Ahead / behind", calc.describe_pace(wa),
                 "—" if summary.equivalent_week is None
                 else f"Balance matches week {summary.equivalent_week:,.2f} of the plan",
                 AMBER if wa is None or wa < 0 else GREEN,
                 "up" if wa is not None and wa >= 0 else "down")

    st.progress(min(float(ach) / 100, 1.0),
                text=f"Week {summary.weeks_completed} target: {calc.format_pct(ach)} achieved")

    section("Actual vs projected balance")
    horizon = max(max(actuals), week, 1)
    log_y = st.toggle("Log scale", value=horizon > 20, key="progress_log")
    st.plotly_chart(progress_figure(capital, multiplier, actuals, horizon, log_y),
                    config=CHART_CONFIG, width="stretch")

    rows = calc.compare_actuals(capital, multiplier, actuals, notes)
    section("Weekly target achievement")
    st.plotly_chart(achievement_figure(rows), config=CHART_CONFIG, width="stretch")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def sidebar(db: TrackerDB) -> None:
    with st.sidebar:
        st.markdown('<div class="brand">💵 USD Money <span>Doubling</span> Tracker</div>'
                    '<div class="muted">Weekly compounding challenge</div>', unsafe_allow_html=True)
        st.write("")
        st.radio("Navigate", list(PAGES), format_func=PAGES.get, key="page",
                 label_visibility="collapsed")
        st.divider()
        st.markdown("**Challenge settings**")
        st.number_input("Initial capital (USD)", min_value=0.01, max_value=float(calc.MAX_CAPITAL),
                        step=1.0, format="%.2f", key="capital", on_change=on_settings_change)
        st.number_input("Weekly multiplication factor", min_value=float(calc.MIN_MULTIPLIER),
                        max_value=float(calc.MAX_MULTIPLIER), step=0.1, format="%.2f",
                        key="multiplier", on_change=on_settings_change,
                        help="2 means your balance doubles every week.")
        st.session_state.week_sidebar = st.session_state.week
        st.number_input("Selected week", min_value=0, max_value=calc.MAX_WEEKS, step=1,
                        key="week_sidebar", on_change=on_week_change, args=("week_sidebar",))
        st.button("Reset to $10 × 2", on_click=reset_defaults, width="stretch")
        st.divider()
        icon = "🟡" if db.is_sqlite else "🟢"
        st.caption(f"{icon} Storage: {db.description}")


def main() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    try:
        db = get_database()
    except DatabaseError as exc:
        st.error(f"The database could not be opened. {exc}")
        st.stop()

    init_state(db)
    sidebar(db)

    try:
        capital = calc.validate_capital(st.session_state.capital)
        multiplier = calc.validate_multiplier(st.session_state.multiplier)
        week = calc.validate_week(st.session_state.week)
    except calc.ValidationError as exc:
        st.error(f"Please check your settings: {exc}")
        st.stop()

    page = st.session_state.page
    try:
        if page == "dashboard":
            page_dashboard(capital, multiplier, week, db)
        elif page == "calculator":
            page_calculator(capital, multiplier)
        elif page == "table":
            page_table(capital, multiplier, week)
        elif page == "chart":
            page_chart(capital, multiplier, week)
        elif page == "tracking":
            page_tracking(capital, multiplier, db)
        elif page == "progress":
            page_progress(capital, multiplier, week, db)
    except DatabaseError as exc:
        st.error(f"A database error occurred: {exc}")
    except calc.ValidationError as exc:
        st.error(str(exc))
    except Exception as exc:  # last-resort guard so the dashboard never shows a raw traceback
        st.error("Something went wrong while drawing this page.")
        with st.expander("Technical details"):
            st.exception(exc)


main()
