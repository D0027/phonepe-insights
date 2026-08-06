"""
PhonePe Transaction Insights — Streamlit Dashboard (Premium Edition v2)
======================================================================
Run with:
    streamlit run dashboard/app.py

FIXES applied vs original:
  FIX 1 (etl.py mirror) — gitpython auto-install already present here, kept.
  FIX 2 — Removed the dead/redundant outer `year_quarter` re-assignment block
           after get_filtered_aggs(). The column is already built inside the
           function; the outer check was unreachable for the non-empty path and
           caused a KeyError crash on the stacked-chart tab when df_type_q was
           empty but df_quarterly was not.
  FIX 3 — Insurance "Top States" SQL now respects sel_years / sel_quarters
           sidebar filters instead of silently querying the entire table.
  FIX 4 (NEW) — load_data() now validates ALL required tables exist in the
           committed .db before trusting it. If incomplete/stale, deletes and
           rebuilds from source instead of silently serving a broken DB.
           This was the root cause of "no such table: aggregated_user".
  FIX 5 (NEW) — df_brand / df_user_raw no longer run raw SQL directly against
           `conn` (which crashes hard if the table is missing). They're now
           built from TABLE_MAP with pandas groupby, with a graceful fallback.

NEW FEATURES:
  - Sidebar "🔄 Refresh Data" button — clears cache, forces DB reload live.
  - CSV download buttons on the Overview table and Top States chart.
  - YoY delta badges on the 5 headline KPI metrics.
  - Data freshness caption (row counts + last DB modified time).
"""

import os, json, sqlite3, subprocess, sys, warnings
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

warnings.filterwarnings("ignore")

# ── Config ────────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).resolve().parent.parent
DB_PATH    = BASE_DIR / "data" / "phonepe_pulse.db"
CLONE_PATH = BASE_DIR / "data" / "pulse"
REPO_URL   = "https://github.com/PhonePe/pulse.git"

REQUIRED_TABLES = {
    "aggregated_transaction", "aggregated_user", "aggregated_insurance",
    "map_transaction", "map_user", "map_insurance",
    "top_transaction", "top_user", "top_insurance",
}

# ── Design Tokens ─────────────────────────────────────────────────────────────
C_BG        = "#07050F"
C_SURFACE   = "#0E0A1A"
C_CARD      = "#130F22"
C_CARD2     = "#1A1530"
C_BORDER    = "#241E3A"
C_BORDER2   = "#2F2850"
C_PURPLE    = "#9D6FFF"
C_PURPLE2   = "#7C3AED"
C_PURPLE3   = "#5B21B6"
C_INDIGO    = "#6366F1"
C_PINK      = "#F472B6"
C_ORANGE    = "#FB923C"
C_GREEN     = "#34D399"
C_TEAL      = "#22D3EE"
C_YELLOW    = "#FBBF24"
C_TEXT      = "#EDE9F8"
C_TEXT2     = "#C4BAE0"
C_MUTED     = "#7B6FA0"
C_MUTED2    = "#5A5278"
C_ACCENT    = "#B794F4"
C_ACCENT2   = "#C4B5FD"

# ── Plotly Base Layout ────────────────────────────────────────────────────────
PLOTLY_BASE = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="'Sora', sans-serif", color=C_TEXT2, size=12),
    title_font=dict(family="'Sora', sans-serif", color=C_TEXT, size=14, weight=600),
    hoverlabel=dict(bgcolor=C_CARD2, bordercolor=C_BORDER2, font=dict(color=C_TEXT, size=12, family="'Sora', sans-serif")),
    margin=dict(l=16, r=16, t=48, b=16),
    legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=C_MUTED, size=11), bordercolor="rgba(0,0,0,0)"),
    xaxis=dict(gridcolor=C_BORDER, linecolor=C_BORDER, tickcolor="rgba(0,0,0,0)", color=C_MUTED, zeroline=False),
    yaxis=dict(gridcolor=C_BORDER, linecolor="rgba(0,0,0,0)", tickcolor="rgba(0,0,0,0)", color=C_MUTED, zeroline=False),
    coloraxis=dict(colorbar=dict(
        tickfont=dict(color=C_MUTED, size=10),
        title=dict(font=dict(color=C_MUTED)),
        bgcolor="rgba(0,0,0,0)",
        bordercolor=C_BORDER,
    )),
)

def layout(**overrides):
    """Merge PLOTLY_BASE with per-chart overrides. Overrides always win."""
    merged = {**PLOTLY_BASE}
    for k, v in overrides.items():
        if k in merged and isinstance(merged[k], dict) and isinstance(v, dict):
            merged[k] = {**merged[k], **v}
        else:
            merged[k] = v
    return merged

# ── Page Config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="PhonePe Insights",
    page_icon="💜",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(f"""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Sora:wght@300;400;500;600;700;800&family=Bricolage+Grotesque:opsz,wght@12..96,300;12..96,400;12..96,500;12..96,600;12..96,700;12..96,800&family=JetBrains+Mono:wght@400;500&display=swap');

  *, *::before, *::after {{ box-sizing: border-box; }}

  html, body, [class*="css"] {{
    font-family: 'Sora', sans-serif;
    background-color: {C_BG};
    color: {C_TEXT};
  }}

  .stApp {{
    background: radial-gradient(ellipse 120% 60% at 50% -10%, rgba(124,58,237,0.18) 0%, transparent 60%),
                radial-gradient(ellipse 80% 40% at 100% 80%, rgba(244,114,182,0.07) 0%, transparent 50%),
                {C_BG};
  }}

  /* ── Sidebar ── */
  section[data-testid="stSidebar"] {{
    background: linear-gradient(180deg, {C_SURFACE} 0%, {C_BG} 100%);
    border-right: 1px solid {C_BORDER};
  }}
  section[data-testid="stSidebar"] * {{ color: {C_TEXT} !important; }}
  section[data-testid="stSidebar"] .stRadio > div {{ gap: 2px !important; }}
  section[data-testid="stSidebar"] .stRadio label {{
    padding: 10px 16px !important;
    border-radius: 10px !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    color: {C_MUTED} !important;
    transition: all 0.2s ease !important;
    cursor: pointer !important;
    border: 1px solid transparent !important;
    margin: 1px 0 !important;
  }}
  section[data-testid="stSidebar"] .stRadio label:hover {{
    background: {C_CARD} !important;
    color: {C_TEXT} !important;
    border-color: {C_BORDER} !important;
  }}
  section[data-testid="stSidebar"] .stRadio [data-checked="true"] + label,
  section[data-testid="stSidebar"] .stRadio label[data-baseweb="radio"]:has(input:checked) {{
    background: linear-gradient(135deg, rgba(124,58,237,0.25), rgba(99,102,241,0.15)) !important;
    color: {C_ACCENT2} !important;
    border-color: rgba(157,111,255,0.35) !important;
  }}
  section[data-testid="stSidebar"] .stRadio [data-testid="stMarkdownContainer"] p {{ margin: 0 !important; }}

  /* ── Metrics ── */
  div[data-testid="metric-container"] {{
    background: linear-gradient(135deg, {C_CARD} 0%, {C_CARD2} 100%);
    border: 1px solid {C_BORDER};
    border-top: 1px solid {C_BORDER2};
    border-radius: 16px;
    padding: 20px 24px;
    position: relative;
    overflow: hidden;
    transition: transform 0.25s ease, box-shadow 0.25s ease;
  }}
  div[data-testid="metric-container"]::before {{
    content: '';
    position: absolute;
    inset: 0;
    border-radius: 16px;
    background: radial-gradient(circle at 30% 20%, rgba(157,111,255,0.08) 0%, transparent 60%);
  }}
  div[data-testid="metric-container"]:hover {{
    transform: translateY(-3px);
    box-shadow: 0 12px 40px rgba(124,58,237,0.25), 0 0 0 1px rgba(157,111,255,0.2);
  }}
  div[data-testid="metric-container"] label {{
    color: {C_MUTED} !important;
    font-size: 11px !important;
    font-weight: 600 !important;
    letter-spacing: 0.12em !important;
    text-transform: uppercase !important;
  }}
  div[data-testid="metric-container"] div[data-testid="stMetricValue"] {{
    color: {C_TEXT} !important;
    font-size: 26px !important;
    font-weight: 700 !important;
    font-family: 'Bricolage Grotesque', sans-serif !important;
    line-height: 1.1 !important;
  }}
  div[data-testid="metric-container"] div[data-testid="stMetricDelta"] {{
    font-size: 12px !important;
  }}

  /* ── Tabs ── */
  .stTabs [data-baseweb="tab-list"] {{
    background: {C_CARD};
    border-radius: 14px;
    border: 1px solid {C_BORDER};
    padding: 5px;
    gap: 3px;
  }}
  .stTabs [data-baseweb="tab"] {{
    background: transparent;
    border-radius: 10px;
    color: {C_MUTED};
    font-weight: 500;
    font-size: 13px;
    padding: 8px 18px;
    border: none !important;
    transition: all 0.2s;
  }}
  .stTabs [data-baseweb="tab"]:hover {{ color: {C_TEXT2}; background: {C_CARD2}; }}
  .stTabs [aria-selected="true"] {{
    background: linear-gradient(135deg, {C_PURPLE2}, {C_INDIGO}) !important;
    color: white !important;
    box-shadow: 0 4px 14px rgba(124,58,237,0.4) !important;
  }}

  /* ── Widgets ── */
  .stMultiSelect [data-baseweb="select"] {{
    background: {C_CARD} !important;
    border-color: {C_BORDER} !important;
    border-radius: 10px !important;
  }}
  .stSlider [data-testid="stTickBar"] {{ color: {C_MUTED}; }}
  .stDataFrame {{
    border-radius: 14px;
    overflow: hidden;
    border: 1px solid {C_BORDER} !important;
  }}

  /* ── Buttons (NEW) ── */
  .stButton > button, .stDownloadButton > button {{
    background: linear-gradient(135deg, {C_PURPLE2}, {C_INDIGO}) !important;
    color: white !important;
    border: none !important;
    border-radius: 10px !important;
    font-size: 12.5px !important;
    font-weight: 600 !important;
    padding: 8px 14px !important;
    transition: all 0.2s ease !important;
    box-shadow: 0 2px 10px rgba(124,58,237,0.25) !important;
  }}
  .stButton > button:hover, .stDownloadButton > button:hover {{
    transform: translateY(-1px);
    box-shadow: 0 6px 18px rgba(124,58,237,0.4) !important;
  }}

  /* ── Insight card ── */
  .insight-card {{
    background: linear-gradient(135deg, rgba(19,15,34,0.9), rgba(26,21,48,0.9));
    border: 1px solid {C_BORDER};
    border-left: 3px solid {C_PURPLE};
    border-radius: 12px;
    padding: 13px 18px;
    margin: 5px 0;
    font-size: 13.5px;
    color: {C_TEXT2};
    line-height: 1.65;
    backdrop-filter: blur(8px);
  }}
  .insight-card b {{ color: {C_ACCENT2}; font-weight: 600; }}

  /* ── Section headers ── */
  .section-title {{
    font-family: 'Bricolage Grotesque', sans-serif;
    font-size: 28px;
    font-weight: 700;
    color: {C_TEXT};
    margin-bottom: 2px;
    letter-spacing: -0.02em;
    line-height: 1.2;
  }}
  .section-sub {{
    color: {C_MUTED};
    font-size: 13px;
    margin-bottom: 22px;
    letter-spacing: 0.01em;
  }}

  /* ── KPI badge ── */
  .kpi-pill {{
    display: inline-block;
    background: linear-gradient(135deg, rgba(157,111,255,0.12), rgba(99,102,241,0.08));
    border: 1px solid rgba(157,111,255,0.2);
    border-radius: 20px;
    padding: 3px 12px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: {C_ACCENT};
    margin-bottom: 16px;
  }}

  /* ── Page header ── */
  .page-header {{
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    margin-bottom: 10px;
    padding-bottom: 16px;
    border-bottom: 1px solid {C_BORDER};
  }}
  .page-title {{
    font-family: 'Bricolage Grotesque', sans-serif;
    font-size: 32px;
    font-weight: 800;
    color: {C_TEXT};
    line-height: 1.1;
    letter-spacing: -0.03em;
  }}
  .page-sub {{
    font-size: 13px;
    color: {C_MUTED};
    margin-top: 5px;
    letter-spacing: 0.01em;
  }}
  .live-badge {{
    display: flex;
    align-items: center;
    gap: 7px;
    font-size: 12px;
    color: {C_MUTED};
    background: {C_CARD};
    padding: 7px 16px;
    border-radius: 24px;
    border: 1px solid {C_BORDER};
    font-family: 'JetBrains Mono', monospace;
    font-weight: 500;
  }}
  .live-dot {{
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: {C_GREEN};
    box-shadow: 0 0 6px {C_GREEN};
    animation: pulse-dot 2s infinite;
  }}
  @keyframes pulse-dot {{
    0%, 100% {{ opacity: 1; transform: scale(1); }}
    50% {{ opacity: 0.5; transform: scale(0.85); }}
  }}

  /* ── Divider ── */
  hr {{
    border: none !important;
    border-top: 1px solid {C_BORDER} !important;
    margin: 18px 0 !important;
  }}

  /* ── Alerts ── */
  .stAlert {{
    background: {C_CARD} !important;
    border-color: {C_BORDER} !important;
    color: {C_TEXT} !important;
    border-radius: 12px !important;
  }}

  /* ── Sidebar brand ── */
  .sidebar-brand {{
    padding: 4px 0 24px;
  }}
  .brand-name {{
    font-family: 'Bricolage Grotesque', sans-serif;
    font-size: 24px;
    font-weight: 800;
    background: linear-gradient(135deg, {C_ACCENT2}, {C_PINK});
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    line-height: 1.1;
  }}
  .brand-sub {{
    font-size: 10px;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: {C_MUTED2} !important;
    margin-top: 4px;
    -webkit-text-fill-color: {C_MUTED2} !important;
  }}

  /* ── Nav label ── */
  .nav-label {{
    font-size: 10px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: {C_MUTED2};
    font-weight: 600;
    margin: 16px 0 8px 4px;
  }}

  /* ── Filter label ── */
  .filter-label {{
    font-size: 10px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: {C_MUTED2};
    font-weight: 600;
    margin: 0 0 8px 4px;
  }}

  /* ── Chart wrap ── */
  .chart-wrap {{
    background: linear-gradient(160deg, {C_CARD}, {C_CARD2});
    border: 1px solid {C_BORDER};
    border-radius: 18px;
    padding: 4px;
    margin-bottom: 14px;
  }}

  /* ── Scrollbar ── */
  ::-webkit-scrollbar {{ width: 5px; height: 5px; }}
  ::-webkit-scrollbar-track {{ background: transparent; }}
  ::-webkit-scrollbar-thumb {{ background: {C_BORDER2}; border-radius: 3px; }}
  ::-webkit-scrollbar-thumb:hover {{ background: {C_MUTED2}; }}

  /* ── Plotly chart border ── */
  .stPlotlyChart {{ border-radius: 16px; overflow: hidden; }}

  /* ── Table styling ── */
  .stDataFrame [data-testid="stDataFrameResizable"] {{
    background: {C_CARD} !important;
  }}

  /* ── Freshness caption (NEW) ── */
  .freshness-caption {{
    font-size: 11px;
    color: {C_MUTED2};
    font-family: 'JetBrains Mono', monospace;
    margin-top: 6px;
  }}
</style>
""", unsafe_allow_html=True)


# ── Helpers ───────────────────────────────────────────────────────────────────
def clean_state(s): return s.replace("-", " ").title()

def _state_path(dp, *parts):
    p1 = os.path.join(dp, *parts, "country", "india", "state")
    p2 = os.path.join(dp, *parts, "india", "state")
    return p1 if os.path.exists(p1) else (p2 if os.path.exists(p2) else None)

def _iter_state_files(base):
    if not base: return
    for state in os.listdir(base):
        sp = os.path.join(base, state)
        if not os.path.isdir(sp): continue
        for year in os.listdir(sp):
            yp = os.path.join(sp, year)
            if not os.path.isdir(yp): continue
            for fname in os.listdir(yp):
                if fname.endswith(".json"):
                    yield clean_state(state), int(year), int(fname.replace(".json", "")), os.path.join(yp, fname)

def insight(text):
    st.markdown(f'<div class="insight-card">💡 {text}</div>', unsafe_allow_html=True)

def section_header(title, sub=""):
    st.markdown(f'<div class="section-title">{title}</div>', unsafe_allow_html=True)
    if sub:
        st.markdown(f'<div class="section-sub">{sub}</div>', unsafe_allow_html=True)

@st.cache_data
def to_csv_bytes(df: pd.DataFrame) -> bytes:
    """NEW: cache CSV encoding so repeated download-button renders are cheap."""
    return df.to_csv(index=False).encode("utf-8")


# ── Parsers ───────────────────────────────────────────────────────────────────
def parse_aggregated_transaction(dp):
    base, rows = _state_path(dp, "aggregated", "transaction"), []
    for state, year, q, fp in _iter_state_files(base):
        with open(fp) as f: d = json.load(f)
        for item in (d.get("data") or {}).get("transactionData", []):
            pi = item.get("paymentInstruments", [{}])[0]
            rows.append({"state": state, "year": year, "quarter": q,
                "transaction_type": item.get("name", ""),
                "transaction_count": pi.get("count", 0),
                "transaction_amount": pi.get("amount", 0)})
    return pd.DataFrame(rows)

def parse_aggregated_user(dp):
    base, rows = _state_path(dp, "aggregated", "user"), []
    for state, year, q, fp in _iter_state_files(base):
        with open(fp) as f: d = json.load(f)
        agg = (d.get("data") or {}).get("aggregated", {})
        reg = agg.get("registeredUsers", 0); opens = agg.get("appOpens", 0)
        for bi in ((d.get("data") or {}).get("usersByDevice") or []):
            rows.append({"state": state, "year": year, "quarter": q,
                "brand": bi.get("brand", "Others"), "brand_count": bi.get("count", 0),
                "brand_percentage": bi.get("percentage", 0),
                "registered_users": reg, "app_opens": opens})
    return pd.DataFrame(rows)

def parse_aggregated_insurance(dp):
    base, rows = _state_path(dp, "aggregated", "insurance"), []
    for state, year, q, fp in _iter_state_files(base):
        with open(fp) as f: d = json.load(f)
        for item in (d.get("data") or {}).get("transactionData", []):
            pi = item.get("paymentInstruments", [{}])[0]
            rows.append({"state": state, "year": year, "quarter": q,
                "insurance_type": item.get("name", ""),
                "insurance_count": pi.get("count", 0), "insurance_amount": pi.get("amount", 0)})
    return pd.DataFrame(rows)

def parse_map_transaction(dp):
    base, rows = _state_path(dp, "map", "transaction", "hover"), []
    for state, year, q, fp in _iter_state_files(base):
        with open(fp) as f: d = json.load(f)
        for item in (d.get("data") or {}).get("hoverDataList", []):
            m = item.get("metric") or [{}]
            rows.append({"state": state, "year": year, "quarter": q,
                "district": item.get("name", "").replace("-", " ").title(),
                "transaction_count": m[0].get("count", 0) if m else 0,
                "transaction_amount": m[0].get("amount", 0) if m else 0})
    return pd.DataFrame(rows)

def parse_map_user(dp):
    base, rows = _state_path(dp, "map", "user", "hover"), []
    for state, year, q, fp in _iter_state_files(base):
        with open(fp) as f: d = json.load(f)
        hover = (d.get("data") or {}).get("hoverData") or {}
        for dist, vals in hover.items():
            rows.append({"state": state, "year": year, "quarter": q,
                "district": dist.replace("-", " ").title(),
                "registered_users": vals.get("registeredUsers", 0),
                "app_opens": vals.get("appOpens", 0)})
    return pd.DataFrame(rows)

def parse_map_insurance(dp):
    base, rows = _state_path(dp, "map", "insurance", "hover"), []
    for state, year, q, fp in _iter_state_files(base):
        with open(fp) as f: d = json.load(f)
        for item in (d.get("data") or {}).get("hoverDataList", []):
            m = item.get("metric") or [{}]
            rows.append({"state": state, "year": year, "quarter": q,
                "district": item.get("name", "").replace("-", " ").title(),
                "insurance_count": m[0].get("count", 0) if m else 0,
                "insurance_amount": m[0].get("amount", 0) if m else 0})
    return pd.DataFrame(rows)

def parse_top_transaction(dp):
    base, rows = _state_path(dp, "top", "transaction"), []
    for state, year, q, fp in _iter_state_files(base):
        with open(fp) as f: d = json.load(f)
        for item in (d.get("data") or {}).get("pincodes", []):
            m = item.get("metric", {})
            rows.append({"state": state, "year": year, "quarter": q,
                "pincode": item.get("entityName", ""),
                "transaction_count": m.get("count", 0), "transaction_amount": m.get("amount", 0)})
    return pd.DataFrame(rows)

def parse_top_user(dp):
    base, rows = _state_path(dp, "top", "user"), []
    for state, year, q, fp in _iter_state_files(base):
        with open(fp) as f: d = json.load(f)
        for item in (d.get("data") or {}).get("districts", []):
            rows.append({"state": state, "year": year, "quarter": q,
                "district": item.get("name", "").replace("-", " ").title(),
                "registered_users": item.get("registeredUsers", 0)})
    return pd.DataFrame(rows)

def parse_top_insurance(dp):
    base, rows = _state_path(dp, "top", "insurance"), []
    for state, year, q, fp in _iter_state_files(base):
        with open(fp) as f: d = json.load(f)
        for item in (d.get("data") or {}).get("pincodes", []):
            m = item.get("metric", {})
            rows.append({"state": state, "year": year, "quarter": q,
                "pincode": item.get("entityName", ""),
                "insurance_count": m.get("count", 0), "insurance_amount": m.get("amount", 0)})
    return pd.DataFrame(rows)


# ── Data Loader ───────────────────────────────────────────────────────────────
def _rebuild_from_source():
    """NEW: split out so both the fallback path AND the 'incomplete DB' path can call it."""
    try:
        from git import Repo
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "gitpython", "-q"])
        from git import Repo

    if not CLONE_PATH.exists():
        with st.spinner("⏳ Cloning PhonePe Pulse repo (first run ~1–2 min)…"):
            Repo.clone_from(REPO_URL, str(CLONE_PATH))

    data_path = str(CLONE_PATH / "data")
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)

    PARSERS = [
        ("aggregated_transaction", parse_aggregated_transaction),
        ("aggregated_user",        parse_aggregated_user),
        ("aggregated_insurance",   parse_aggregated_insurance),
        ("map_transaction",        parse_map_transaction),
        ("map_user",               parse_map_user),
        ("map_insurance",          parse_map_insurance),
        ("top_transaction",        parse_top_transaction),
        ("top_user",               parse_top_user),
        ("top_insurance",          parse_top_insurance),
    ]
    tmap = {}
    for tname, fn in PARSERS:
        try:
            df = fn(data_path)
            if not df.empty:
                df.to_sql(tname, conn, if_exists="replace", index=False)
            tmap[tname] = df
        except Exception as e:
            st.warning(f"⚠️ {tname}: {e}")
            tmap[tname] = pd.DataFrame()
    return conn, tmap


@st.cache_resource(show_spinner=False)
def load_data():
    if DB_PATH.exists():
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        tables = set(pd.read_sql("SELECT name FROM sqlite_master WHERE type='table'", conn)["name"].tolist())

        # FIX 4 (NEW): validate the committed/cached db actually has every table
        # we depend on. A partial or stale db (e.g. one committed mid-build, or
        # one where a parser failed silently in a previous run) used to get
        # trusted blindly here — that's exactly what caused
        # "no such table: aggregated_user" in production.
        if REQUIRED_TABLES.issubset(tables):
            tmap = {t: pd.read_sql(f"SELECT * FROM {t}", conn) for t in tables}
            return conn, tmap
        else:
            missing = REQUIRED_TABLES - tables
            st.warning(f"⚠️ Local DB incomplete (missing: {', '.join(sorted(missing))}). Rebuilding from source…")
            conn.close()
            try:
                DB_PATH.unlink()
            except OSError:
                pass
            return _rebuild_from_source()

    return _rebuild_from_source()


def clear_data_cache():
    """NEW: powers the sidebar Refresh Data button."""
    load_data.clear()


with st.spinner(""):
    conn, TABLE_MAP = load_data()


def sql(q): return pd.read_sql_query(q, conn)


# ── Pre-Aggregations ──────────────────────────────────────────────────────────
df_agg_txn  = TABLE_MAP.get("aggregated_transaction", pd.DataFrame())
df_agg_user = TABLE_MAP.get("aggregated_user",        pd.DataFrame())
df_agg_ins  = TABLE_MAP.get("aggregated_insurance",   pd.DataFrame())
df_map_txn  = TABLE_MAP.get("map_transaction",        pd.DataFrame())
df_top_txn  = TABLE_MAP.get("top_transaction",        pd.DataFrame())

# ── Static (unfiltered) aggregations ─────────────────────────────────────────
# FIX 5 (NEW): built from TABLE_MAP via pandas instead of raw SQL against
# `conn`. Raw sql("... FROM aggregated_user ...") would hard-crash the entire
# app if that one table was ever missing. This degrades gracefully instead.
if not df_agg_user.empty:
    df_brand = (
        df_agg_user.groupby("brand", as_index=False)["brand_count"]
        .sum()
        .rename(columns={"brand_count": "total_users"})
        .sort_values("total_users", ascending=False)
    )
    df_user_raw = (
        df_agg_user.groupby(["state", "year", "quarter"], as_index=False)
        .agg(reg=("registered_users", "max"), opens=("app_opens", "max"))
    )
else:
    st.error("⚠️ `aggregated_user` table is empty this run — device/engagement charts will be unavailable.")
    df_brand = pd.DataFrame(columns=["brand", "total_users"])
    df_user_raw = pd.DataFrame(columns=["state", "year", "quarter", "reg", "opens"])

_df_user_all = df_user_raw.groupby("state", as_index=False).agg(total_registered=("reg","sum"), total_app_opens=("opens","sum"))
_df_user_all["engagement_rate"] = (_df_user_all["total_app_opens"] / _df_user_all["total_registered"].replace(0, np.nan)).round(2)

if not df_agg_ins.empty:
    df_ins_trend = (
        df_agg_ins.groupby(["year", "quarter"], as_index=False)
        .agg(total_ins_count=("insurance_count", "sum"), total_ins_amount=("insurance_amount", "sum"))
        .sort_values(["year", "quarter"])
    )
    df_ins_trend["year_quarter"] = df_ins_trend["year"].astype(str) + "-Q" + df_ins_trend["quarter"].astype(str)
else:
    df_ins_trend = pd.DataFrame()


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(f"""
    <div class="sidebar-brand">
      <div class="brand-name">PhonePe</div>
      <div class="brand-sub">Transaction Insights</div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown(f'<div class="nav-label">Navigation</div>', unsafe_allow_html=True)

    page = st.radio(
        "Navigation",
        [
            "🏠  Overview",
            "📊  Transactions",
            "👤  Users & Devices",
            "🗺️  Geographic",
            "🛡️  Insurance",
            "📈  Growth & Trends",
        ],
        label_visibility="collapsed"
    )

    st.markdown("<hr>", unsafe_allow_html=True)
    st.markdown(f'<div class="filter-label">Filters</div>', unsafe_allow_html=True)

    if not df_agg_txn.empty:
        _all_years    = sorted(df_agg_txn["year"].unique())
        _all_quarters = sorted(df_agg_txn["quarter"].unique())
        sel_years    = st.multiselect("Years",    _all_years,    default=_all_years)
        sel_quarters = st.multiselect("Quarters", _all_quarters, default=_all_quarters)
        if not sel_years:    sel_years    = _all_years
        if not sel_quarters: sel_quarters = _all_quarters
    else:
        _all_years = _all_quarters = []
        sel_years = sel_quarters = []

    is_filtered = (not df_agg_txn.empty) and (
        sorted(sel_years) != sorted(_all_years) or
        sorted(sel_quarters) != sorted(_all_quarters)
    )
    if is_filtered:
        yr_str = ", ".join(str(y) for y in sorted(sel_years))
        q_str  = ", ".join(f"Q{q}" for q in sorted(sel_quarters))
        st.markdown(f"""
        <div style="background:rgba(157,111,255,0.12);border:1px solid rgba(157,111,255,0.3);
             border-radius:10px;padding:10px 14px;margin-top:8px;font-size:12px;color:{C_ACCENT2};">
          <div style="font-weight:600;margin-bottom:4px;font-size:11px;text-transform:uppercase;letter-spacing:0.08em;">
            ✦ Active Filter
          </div>
          <div style="color:{C_TEXT2};">Years: <b style="color:{C_ACCENT2};">{yr_str}</b></div>
          <div style="color:{C_TEXT2};">Quarters: <b style="color:{C_ACCENT2};">{q_str}</b></div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<hr>", unsafe_allow_html=True)

    # NEW: Refresh Data button — clears @st.cache_resource so a bad/partial
    # local db can be force-rebuilt without needing a redeploy.
    if st.button("🔄  Refresh Data", use_container_width=True):
        clear_data_cache()
        st.rerun()

    # NEW: data freshness caption
    total_rows = sum(len(d) for d in TABLE_MAP.values())
    db_modified = (
        datetime.fromtimestamp(DB_PATH.stat().st_mtime).strftime("%d %b %Y, %H:%M")
        if DB_PATH.exists() else "N/A"
    )
    st.markdown(
        f'<div class="freshness-caption">📦 {total_rows:,} rows loaded<br>🕒 DB updated: {db_modified}</div>',
        unsafe_allow_html=True
    )

    st.markdown("<hr>", unsafe_allow_html=True)
    st.markdown(f'<div style="font-size:11px;color:{C_MUTED};line-height:1.8;">Source: <a href="https://github.com/PhonePe/pulse" style="color:{C_ACCENT};text-decoration:none;font-weight:500;">PhonePe Pulse</a><br>India · 2018–2023 · SQLite</div>', unsafe_allow_html=True)


# ── Dynamic filtered aggregations ─────────────────────────────────────────────
def filtered_txn():
    if df_agg_txn.empty: return df_agg_txn
    return df_agg_txn[df_agg_txn["year"].isin(sel_years) & df_agg_txn["quarter"].isin(sel_quarters)]

def get_filtered_aggs():
    ft = filtered_txn()
    if ft.empty:
        empty = pd.DataFrame()
        return empty, empty, empty, empty, empty, empty, empty

    df_st = ft.groupby("state", as_index=False).agg(
        total_txn_count=("transaction_count","sum"),
        total_txn_amount=("transaction_amount","sum")
    ).sort_values("total_txn_amount", ascending=False)

    df_tt = ft.groupby("transaction_type", as_index=False).agg(
        total_count=("transaction_count","sum"),
        total_amount=("transaction_amount","sum")
    ).sort_values("total_amount", ascending=False)

    df_q = ft.groupby(["year","quarter"], as_index=False).agg(
        total_count=("transaction_count","sum"),
        total_amount=("transaction_amount","sum")
    ).sort_values(["year","quarter"])
    df_q["year_quarter"] = df_q["year"].astype(str) + "-Q" + df_q["quarter"].astype(str)

    df_tq = ft.groupby(["year","quarter","transaction_type"], as_index=False).agg(
        amount=("transaction_amount","sum")
    ).sort_values(["year","quarter"])
    df_tq["year_quarter"] = df_tq["year"].astype(str) + "-Q" + df_tq["quarter"].astype(str)

    df_y = ft.groupby("year", as_index=False).agg(
        total_count=("transaction_count","sum"),
        total_amount=("transaction_amount","sum")
    ).sort_values("year")
    df_y["count_growth"]  = df_y["total_count"].pct_change()  * 100
    df_y["amount_growth"] = df_y["total_amount"].pct_change() * 100

    df_s = ft.groupby("quarter", as_index=False).agg(
        avg_count=("transaction_count","mean"),
        avg_amount=("transaction_amount","mean")
    ).sort_values("quarter")

    _u = df_user_raw[df_user_raw["quarter"].isin(sel_quarters)]
    df_us = _u.groupby("state", as_index=False).agg(total_registered=("reg","sum"), total_app_opens=("opens","sum"))
    df_us["engagement_rate"] = (df_us["total_app_opens"] / df_us["total_registered"].replace(0, np.nan)).round(2)

    return df_st, df_tt, df_q, df_tq, df_y, df_s, df_us

# Pre-compute for this render
df_state_total, df_type_total, df_quarterly, df_type_q, df_yoy, df_seas, df_user_state = get_filtered_aggs()


# ── Page Header ───────────────────────────────────────────────────────────────
page_label = page.split("  ", 1)[-1] if "  " in page else page

st.markdown(f"""
<div class="page-header">
  <div>
    <div class="page-title">{page_label}</div>
    <div class="page-sub">PhonePe Pulse · India Digital Payments · 2018–2023</div>
  </div>
  <div class="live-badge">
    <div class="live-dot"></div>
    SQLite · Live
  </div>
</div>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  PAGES
# ══════════════════════════════════════════════════════════════════════════════

if "Overview" in page:
    c1, c2, c3, c4, c5 = st.columns(5)
    total_val   = df_state_total["total_txn_amount"].sum() if not df_state_total.empty else 0
    total_cnt   = df_state_total["total_txn_count"].sum() if not df_state_total.empty else 0
    total_users = df_user_state["total_registered"].sum() if not df_user_state.empty else 0
    total_opens = df_user_state["total_app_opens"].sum() if not df_user_state.empty else 0
    n_states    = len(df_state_total)

    # NEW: YoY delta badges — compares latest year vs previous year in the
    # (unfiltered) yearly series so the KPI cards show real momentum.
    delta_val = delta_cnt = None
    if not df_yoy.empty and len(df_yoy) > 1:
        delta_val = f"{df_yoy['amount_growth'].iloc[-1]:.1f}% YoY"
        delta_cnt = f"{df_yoy['count_growth'].iloc[-1]:.1f}% YoY"

    c1.metric("💰 Total Value",       f"₹{total_val/1e12:.1f}T", delta=delta_val)
    c2.metric("🔢 Transactions",      f"{total_cnt/1e9:.2f}B",   delta=delta_cnt)
    c3.metric("👥 Registered Users",  f"{total_users/1e6:.0f}M")
    c4.metric("📲 App Opens",         f"{total_opens/1e9:.1f}B")
    c5.metric("🗺️ States Covered",    str(n_states))

    st.markdown("<br>", unsafe_allow_html=True)
    ca, cb = st.columns([3, 2])

    with ca:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df_quarterly["year_quarter"], y=df_quarterly["total_amount"]/1e12,
            fill="tozeroy",
            fillcolor="rgba(157,111,255,0.10)",
            line=dict(color=C_PURPLE, width=2.5),
            mode="lines",
            hovertemplate="<b>%{x}</b><br>₹%{y:.2f}T<extra></extra>"
        ))
        fig.update_layout(**layout(
            title="Transaction Value Over Time (₹T)",
            height=250,
            margin=dict(l=16, r=16, t=48, b=16),
            xaxis=dict(gridcolor=C_BORDER, showticklabels=True, tickfont=dict(size=9), color=C_MUTED),
            yaxis=dict(gridcolor=C_BORDER, color=C_MUTED),
        ))
        st.plotly_chart(fig, use_container_width=True)

        fig2 = px.pie(df_type_total, values="total_amount", names="transaction_type",
            hole=0.58, title="Value Share by Payment Type",
            color_discrete_sequence=[C_PURPLE, C_INDIGO, C_PINK, C_TEAL, C_ORANGE])
        fig2.update_traces(textposition="outside", textfont_size=11,
            marker=dict(line=dict(color=C_CARD, width=2)))
        fig2.update_layout(**layout(
            height=300,
            showlegend=True,
            margin=dict(l=16, r=16, t=48, b=30),
            legend=dict(orientation="h", yanchor="bottom", y=-0.18, xanchor="center", x=0.5, font=dict(size=10, color=C_MUTED)),
        ))
        st.plotly_chart(fig2, use_container_width=True)

    with cb:
        st.markdown(f'<div style="font-size:10px;font-weight:600;color:{C_MUTED2};letter-spacing:0.14em;text-transform:uppercase;margin-bottom:12px;">Key Insights</div>', unsafe_allow_html=True)
        for txt in [
            "<b>Maharashtra & Karnataka</b> alone account for ~25% of national digital transaction value.",
            "<b>Peer-to-Peer</b> payments dominate — ~45% of volume and ~50% of value.",
            "<b>COVID-19 (2020–21)</b> triggered the sharpest YoY growth inflection in the dataset.",
            "<b>Xiaomi + Samsung</b> serve ~38% of PhonePe's user base — OEM partnerships critical.",
            "<b>Q4 (Oct–Dec)</b> is peak season — Diwali drives amount spikes every year.",
            "<b>Insurance</b> surged post-2020 and remains in early high-growth phase.",
            "<b>Amount growth outpaces count</b> — signals a maturing, higher-value user base.",
        ]:
            insight(txt)

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown(f'<div style="font-size:10px;font-weight:600;color:{C_MUTED2};letter-spacing:0.14em;text-transform:uppercase;margin-bottom:10px;">Dataset Tables</div>', unsafe_allow_html=True)
        tables_df = pd.DataFrame([
            {"Table": n, "Rows": f"{len(d):,}", "Cols": len(d.columns)}
            for n, d in TABLE_MAP.items()
        ])
        st.dataframe(tables_df, use_container_width=True, hide_index=True)

        # NEW: quick export of the table summary
        st.download_button(
            "⬇️  Export Table Summary (CSV)",
            data=to_csv_bytes(tables_df),
            file_name="phonepe_dataset_summary.csv",
            mime="text/csv",
            use_container_width=True,
        )


elif "Transactions" in page:
    tab1, tab2, tab3, tab4 = st.tabs(["  Top States  ", "  Type Distribution  ", "  Quarterly Trend  ", "  Stacked View  "])

    with tab1:
        ft = filtered_txn()
        if ft.empty:
            st.warning("No data for selected filters.")
        else:
            sg = ft.groupby("state", as_index=False).agg(
                total_txn_count=("transaction_count", "sum"),
                total_txn_amount=("transaction_amount", "sum"))
            col1, col2 = st.columns([4, 1])
            with col2:
                n = st.slider("Top N", 5, 36, 12)
                metric_choice = st.radio("Metric", ["Amount", "Count"], index=0)
                # NEW: export the currently-viewed top-N slice
                st.download_button(
                    "⬇️  Export CSV",
                    data=to_csv_bytes(sg.sort_values("total_txn_amount", ascending=False)),
                    file_name="phonepe_states_transactions.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
            with col1:
                metric_col = "total_txn_amount" if metric_choice == "Amount" else "total_txn_count"
                top = sg.nlargest(n, metric_col).sort_values(metric_col)
                scale = 1e12 if metric_choice == "Amount" else 1e6
                suffix = "T" if metric_choice == "Amount" else "M"
                fig = px.bar(top, x=metric_col, y="state", orientation="h",
                    title=f"Top {n} States — Transaction {metric_choice}",
                    color=metric_col,
                    color_continuous_scale=[[0, C_INDIGO], [0.5, C_PURPLE], [1, C_PINK]],
                    text=top[metric_col].apply(lambda x: f"₹{x/scale:.1f}{suffix}" if metric_choice == "Amount" else f"{x/scale:.0f}{suffix}"),
                    labels={metric_col: metric_choice, "state": ""})
                fig.update_traces(textposition="outside", textfont_size=10,
                    marker=dict(line=dict(width=0)))
                fig.update_layout(**layout(
                    height=520,
                    coloraxis_showscale=False,
                    yaxis=dict(gridcolor="rgba(0,0,0,0)", color=C_TEXT2),
                    xaxis=dict(gridcolor=C_BORDER, color=C_MUTED),
                ))
                st.plotly_chart(fig, use_container_width=True)
            insight("Maharashtra leads by a wide margin. Tier-2 states (UP, Bihar) = untapped markets with existing registered user bases.")

    with tab2:
        ft = filtered_txn()
        if not ft.empty:
            tg = ft.groupby("transaction_type", as_index=False).agg(
                total_count=("transaction_count", "sum"),
                total_amount=("transaction_amount", "sum"))
            c1, c2 = st.columns(2)
            colors = [C_PURPLE, C_INDIGO, C_PINK, C_TEAL, C_ORANGE]
            for ax, val_col, title in [
                (c1, "total_count",  "By Transaction Count"),
                (c2, "total_amount", "By Transaction Value (₹)")
            ]:
                fig = px.pie(tg, values=val_col, names="transaction_type", hole=0.52,
                    title=title, color_discrete_sequence=colors)
                fig.update_traces(textposition="outside", pull=[0.03]*len(tg),
                    marker=dict(line=dict(color=C_CARD, width=2)))
                fig.update_layout(**layout(
                    height=380,
                    margin=dict(l=16, r=16, t=48, b=40),
                    legend=dict(orientation="h", yanchor="bottom", y=-0.22, xanchor="center", x=0.5, font=dict(size=10, color=C_MUTED)),
                ))
                ax.plotly_chart(fig, use_container_width=True)
            insight("P2P dominates in both count and value. Financial Services punches above its weight on amount — fewer but high-value transactions.")

    with tab3:
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(go.Scatter(
            x=df_quarterly["year_quarter"], y=df_quarterly["total_count"]/1e6,
            name="Count (M)", fill="tozeroy", fillcolor="rgba(157,111,255,0.12)",
            line=dict(color=C_PURPLE, width=2.5), mode="lines+markers",
            marker=dict(size=5, color=C_PURPLE, line=dict(color=C_BG, width=1.5)),
            hovertemplate="%{x}<br>Count: %{y:.1f}M<extra></extra>"
        ), secondary_y=False)
        fig.add_trace(go.Scatter(
            x=df_quarterly["year_quarter"], y=df_quarterly["total_amount"]/1e12,
            name="Amount (₹T)", line=dict(color=C_ORANGE, width=2.5, dash="dot"),
            mode="lines+markers",
            marker=dict(size=5, symbol="diamond", color=C_ORANGE, line=dict(color=C_BG, width=1.5)),
            hovertemplate="%{x}<br>₹%{y:.2f}T<extra></extra>"
        ), secondary_y=True)
        fig.update_yaxes(title_text="Transaction Count (M)", secondary_y=False, color=C_PURPLE, gridcolor=C_BORDER, zeroline=False)
        fig.update_yaxes(title_text="Transaction Amount (₹T)", secondary_y=True, color=C_ORANGE, gridcolor="rgba(0,0,0,0)", zeroline=False)
        fig.update_layout(**layout(
            title="Quarterly Transaction Growth — 2018 to 2023",
            height=460,
            xaxis=dict(tickangle=-45, gridcolor=C_BORDER, color=C_MUTED),
        ))
        st.plotly_chart(fig, use_container_width=True)
        insight("Exponential post-2020 surge. Amount growth outpacing count signals a maturing, higher-value user base.")

    with tab4:
        if df_type_q.empty:
            st.warning("No transaction type data for selected filters.")
        else:
            pivot = df_type_q.pivot_table(index="year_quarter", columns="transaction_type", values="amount", aggfunc="sum").fillna(0)
            all_p = [f"{y}-Q{q}" for y in sorted(df_agg_txn["year"].unique()) for q in range(1, 5)]
            pivot = pivot.reindex([p for p in all_p if p in pivot.index])
            colors_stack = [C_PURPLE, C_INDIGO, C_PINK, C_TEAL, C_ORANGE]
            fig = go.Figure()
            for i, col in enumerate(pivot.columns):
                fig.add_trace(go.Bar(
                    x=pivot.index, y=pivot[col]/1e12, name=col,
                    marker_color=colors_stack[i % len(colors_stack)],
                    marker=dict(line=dict(width=0)),
                    hovertemplate=f"<b>{col}</b><br>%{{x}}<br>₹%{{y:.2f}}T<extra></extra>"
                ))
            fig.update_layout(**layout(
                barmode="stack",
                title="Transaction Amount by Type — Quarterly Stack (₹T)",
                height=470,
                xaxis=dict(tickangle=-45, gridcolor=C_BORDER, color=C_MUTED),
                yaxis=dict(title="₹ Trillion", gridcolor=C_BORDER, color=C_MUTED),
                legend=dict(orientation="h", yanchor="bottom", y=-0.28, xanchor="center", x=0.5, font=dict(size=10, color=C_MUTED)),
            ))
            st.plotly_chart(fig, use_container_width=True)
            insight("Merchant payments share growing steadily — validating retail UPI adoption. Financial Services uptick visible from 2021.")


elif "Users" in page:
    tab1, tab2, tab3 = st.tabs(["  Brand Share  ", "  Engagement by State  ", "  Reg vs App Opens  "])

    with tab1:
        if df_brand.empty:
            st.info("Device brand data unavailable this run.")
        else:
            c1, c2 = st.columns(2)
            top_brands = df_brand.head(12)

            fig1 = px.bar(top_brands, x="brand", y="total_users",
                title="Registered Users by Device Brand",
                color="total_users",
                color_continuous_scale=[[0, C_INDIGO], [0.5, C_PURPLE], [1, C_PINK]],
                labels={"brand": "Brand", "total_users": "Users"},
                text=top_brands["total_users"].apply(lambda x: f"{x/1e6:.1f}M"))
            fig1.update_traces(textposition="outside", textfont_size=10,
                marker=dict(line=dict(width=0)))
            fig1.update_layout(**layout(
                height=400,
                coloraxis_showscale=False,
                xaxis=dict(tickangle=-30, gridcolor="rgba(0,0,0,0)", color=C_MUTED),
                yaxis=dict(gridcolor=C_BORDER, color=C_MUTED),
            ))
            c1.plotly_chart(fig1, use_container_width=True)

            fig2 = px.pie(top_brands, values="total_users", names="brand",
                title="Brand Market Share", hole=0.48,
                color_discrete_sequence=[C_PURPLE, C_INDIGO, C_PINK, C_TEAL, C_ORANGE,
                                          "#34D399", "#FBBF24", "#60A5FA", "#F87171",
                                          "#A78BFA", "#6EE7B7", "#FCD34D"])
            fig2.update_traces(marker=dict(line=dict(color=C_CARD, width=2)))
            fig2.update_layout(**layout(
                height=400,
                margin=dict(l=16, r=16, t=48, b=16),
                legend=dict(orientation="v", font=dict(size=10, color=C_MUTED)),
            ))
            c2.plotly_chart(fig2, use_container_width=True)
            insight("Xiaomi leads, followed by Samsung and Vivo — mirrors India's OEM landscape. OEM bundling agreements can drive step-change growth.")

    with tab2:
        if df_user_state.empty:
            st.info("Engagement data unavailable this run.")
        else:
            col1, col2 = st.columns([4, 1])
            with col2:
                n_e = st.slider("Top N", 10, len(df_user_state), min(15, len(df_user_state)))
            with col1:
                top_e = df_user_state.nlargest(n_e, "engagement_rate")
                avg_e = df_user_state["engagement_rate"].mean()
                fig = px.bar(top_e.sort_values("engagement_rate"), x="engagement_rate", y="state",
                    orientation="h",
                    title=f"Engagement Rate — Top {n_e} States (App Opens / Registered Users)",
                    color="engagement_rate",
                    color_continuous_scale=[[0, C_INDIGO], [0.5, C_PURPLE], [1, C_PINK]],
                    text=top_e.sort_values("engagement_rate")["engagement_rate"].apply(lambda x: f"{x:.1f}×"),
                    labels={"state": "", "engagement_rate": "Rate"})
                fig.add_vline(x=avg_e, line_dash="dash", line_color=C_ORANGE,
                    annotation_text=f"Avg {avg_e:.1f}×",
                    annotation_font_color=C_ORANGE,
                    annotation_font_size=11)
                fig.update_traces(textposition="outside", textfont_size=10,
                    marker=dict(line=dict(width=0)))
                fig.update_layout(**layout(
                    height=520,
                    coloraxis_showscale=False,
                    yaxis=dict(gridcolor="rgba(0,0,0,0)", color=C_TEXT2),
                    xaxis=dict(gridcolor=C_BORDER, color=C_MUTED),
                ))
                st.plotly_chart(fig, use_container_width=True)
            insight("Delhi, Chandigarh, Goa lead on engagement. UP and Bihar have millions of registered users but low opens — prime re-activation targets.")

    with tab3:
        if df_user_state.empty:
            st.info("Engagement data unavailable this run.")
        else:
            fig = px.scatter(df_user_state, x="total_registered", y="total_app_opens",
                color="engagement_rate", size="total_registered",
                hover_name="state", text="state",
                title="Registered Users vs App Opens — State Level",
                color_continuous_scale=[[0, C_INDIGO], [0.5, C_PURPLE], [1, C_PINK]],
                labels={"total_registered": "Registered Users", "total_app_opens": "App Opens", "engagement_rate": "Engagement"})
            fig.update_traces(textposition="top center", textfont_size=8,
                selector=dict(mode="markers+text"))
            _x = df_user_state["total_registered"].values
            _y = df_user_state["total_app_opens"].values
            _mask = ~(np.isnan(_x) | np.isnan(_y))
            if _mask.sum() > 1:
                _m, _b = np.polyfit(_x[_mask], _y[_mask], 1)
                _xs = np.array([_x[_mask].min(), _x[_mask].max()])
                fig.add_trace(go.Scatter(
                    x=_xs, y=_m * _xs + _b,
                    mode="lines", name="Trend",
                    line=dict(color=C_ORANGE, width=2, dash="dot"),
                    hoverinfo="skip"
                ))
            fig.update_layout(**layout(
                height=540,
                coloraxis_colorbar=dict(
                    title=dict(text="Rate", font=dict(color=C_MUTED)),
                    tickfont=dict(color=C_MUTED),
                ),
            ))
            st.plotly_chart(fig, use_container_width=True)
            insight("Strong overall correlation. States below the trend line = direct revenue leakage — re-activation campaigns have near-zero acquisition cost.")


elif "Geographic" in page:
    tab1, tab2 = st.tabs(["  Top Districts  ", "  Top Pincodes  "])

    with tab1:
        if not df_map_txn.empty:
            df_d = (
                df_map_txn.assign(sd=df_map_txn["state"] + " — " + df_map_txn["district"])
                .groupby("sd", as_index=False)["transaction_amount"].sum()
                .rename(columns={"transaction_amount": "total_amount"})
                .sort_values("total_amount", ascending=False).head(20)
            )
            fig = px.bar(df_d.sort_values("total_amount"), x="total_amount", y="sd",
                orientation="h",
                title="Top 20 Districts — Transaction Amount",
                color="total_amount",
                color_continuous_scale=[[0, C_INDIGO], [0.5, C_PURPLE], [1, C_PINK]],
                text=df_d.sort_values("total_amount")["total_amount"].apply(lambda x: f"₹{x/1e10:.0f}B"),
                labels={"total_amount": "Amount (₹)", "sd": ""})
            fig.update_traces(textposition="outside", textfont_size=9,
                marker=dict(line=dict(width=0)))
            fig.update_layout(**layout(
                height=640,
                coloraxis_showscale=False,
                yaxis=dict(gridcolor="rgba(0,0,0,0)", color=C_TEXT2),
                xaxis=dict(gridcolor=C_BORDER, color=C_MUTED),
            ))
            st.plotly_chart(fig, use_container_width=True)
            insight("Metro districts dominate. Hyperlocal merchant campaigns in top 50 districts compound growth disproportionately.")
        else:
            st.info("Map transaction data not available in this dataset version.")

    with tab2:
        if not df_top_txn.empty:
            df_p = df_top_txn.groupby("pincode", as_index=False).agg(
                total_amount=("transaction_amount", "sum")).nlargest(15, "total_amount")
            fig = px.bar(df_p.sort_values("total_amount"), x="total_amount", y="pincode",
                orientation="h",
                title="Top 15 Pincodes — Transaction Amount",
                color="total_amount",
                color_continuous_scale=[[0, C_INDIGO], [0.5, C_PURPLE], [1, C_PINK]],
                text=df_p.sort_values("total_amount")["total_amount"].apply(lambda x: f"₹{x/1e6:.0f}M"),
                labels={"total_amount": "Amount (₹)", "pincode": "Pincode"})
            fig.update_traces(textposition="outside", textfont_size=10,
                marker=dict(line=dict(width=0)))
            fig.update_layout(**layout(
                height=520,
                coloraxis_showscale=False,
                yaxis=dict(gridcolor="rgba(0,0,0,0)", color=C_TEXT2),
                xaxis=dict(gridcolor=C_BORDER, color=C_MUTED),
            ))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Top transaction (pincode) data not available.")


elif "Insurance" in page:
    if df_ins_trend.empty:
        st.info("Insurance aggregated data not present in this dataset version.")
    else:
        tab1, tab2 = st.tabs(["  Growth Over Time  ", "  Top States  "])

        with tab1:
            fig = make_subplots(specs=[[{"secondary_y": True}]])
            fig.add_trace(go.Scatter(
                x=df_ins_trend["year_quarter"], y=df_ins_trend["total_ins_amount"]/1e9,
                name="Premium (₹B)", fill="tozeroy", fillcolor="rgba(52,211,153,0.10)",
                line=dict(color=C_GREEN, width=2.5), mode="lines+markers",
                marker=dict(size=5, color=C_GREEN, line=dict(color=C_BG, width=1.5)),
                hovertemplate="%{x}<br>₹%{y:.2f}B<extra></extra>"
            ), secondary_y=False)
            fig.add_trace(go.Bar(
                x=df_ins_trend["year_quarter"], y=df_ins_trend["total_ins_count"]/1e3,
                name="Policies (K)", opacity=0.35,
                marker_color=C_TEAL,
                marker=dict(line=dict(width=0)),
                hovertemplate="%{x}<br>%{y:.1f}K policies<extra></extra>"
            ), secondary_y=True)
            fig.update_yaxes(title_text="Premium (₹B)", secondary_y=False, color=C_GREEN, gridcolor=C_BORDER, zeroline=False)
            fig.update_yaxes(title_text="Policy Count (K)", secondary_y=True, color=C_TEAL, gridcolor="rgba(0,0,0,0)", zeroline=False)
            fig.update_layout(**layout(
                title="Insurance Growth — Premium vs Policy Count",
                height=460,
                xaxis=dict(tickangle=-45, gridcolor=C_BORDER, color=C_MUTED),
            ))
            st.plotly_chart(fig, use_container_width=True)
            insight("Surged post-2020. India's insurance penetration is ~4% of GDP vs 11% in developed markets — massive headroom for contextual cross-sell.")

        with tab2:
            if not df_agg_ins.empty:
                ins_filtered = df_agg_ins[
                    df_agg_ins["year"].isin(sel_years) & df_agg_ins["quarter"].isin(sel_quarters)
                ]
                if ins_filtered.empty:
                    st.warning("No insurance data for the selected year/quarter filters.")
                else:
                    ins_s = (
                        ins_filtered.groupby("state", as_index=False)["insurance_amount"]
                        .sum().rename(columns={"insurance_amount": "amt"})
                        .sort_values("amt", ascending=False).head(15)
                    )
                    fig = px.bar(ins_s.sort_values("amt"), x="amt", y="state", orientation="h",
                        title="Top 15 States — Insurance Premium (filtered)",
                        color="amt",
                        color_continuous_scale=[[0, "#065F46"], [0.5, C_GREEN], [1, "#6EE7B7"]],
                        text=ins_s.sort_values("amt")["amt"].apply(lambda x: f"₹{x/1e6:.0f}M"),
                        labels={"amt": "Premium (₹)", "state": ""})
                    fig.update_traces(textposition="outside", textfont_size=10,
                        marker=dict(line=dict(width=0)))
                    fig.update_layout(**layout(
                        height=520,
                        coloraxis_showscale=False,
                        yaxis=dict(gridcolor="rgba(0,0,0,0)", color=C_TEXT2),
                        xaxis=dict(gridcolor=C_BORDER, color=C_MUTED),
                    ))
                    st.plotly_chart(fig, use_container_width=True)


elif "Growth" in page:
    tab1, tab2, tab3 = st.tabs(["  YoY Growth  ", "  Seasonality  ", "  Distribution  "])

    with tab1:
        if df_yoy.empty:
            st.warning("No data for selected filters.")
        else:
            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=df_yoy["year"].astype(str), y=df_yoy["count_growth"].fillna(0),
                name="Count Growth %",
                marker_color=C_PURPLE,
                marker=dict(line=dict(width=0)),
                opacity=0.88,
                text=df_yoy["count_growth"].fillna(0).apply(lambda x: f"{x:.0f}%"),
                textposition="outside", textfont_size=11
            ))
            fig.add_trace(go.Bar(
                x=df_yoy["year"].astype(str), y=df_yoy["amount_growth"].fillna(0),
                name="Amount Growth %",
                marker_color=C_ORANGE,
                marker=dict(line=dict(width=0)),
                opacity=0.88,
                text=df_yoy["amount_growth"].fillna(0).apply(lambda x: f"{x:.0f}%"),
                textposition="outside", textfont_size=11
            ))
            fig.add_hline(y=0, line_color=C_MUTED2, line_width=0.8)
            fig.update_layout(**layout(
                barmode="group",
                title="Year-over-Year Transaction Growth Rate",
                height=440,
                yaxis=dict(title="Growth (%)", gridcolor=C_BORDER, color=C_MUTED),
                xaxis=dict(gridcolor="rgba(0,0,0,0)", color=C_MUTED),
            ))
            st.plotly_chart(fig, use_container_width=True)
            insight("2020–21 = peak COVID surge. Moderating post-2021 from a higher base. Amount consistently outpacing count confirms maturing user base.")

    with tab2:
        if df_seas.empty:
            st.warning("No data for selected filters.")
        else:
            q_labels = ["Q1 (Jan–Mar)", "Q2 (Apr–Jun)", "Q3 (Jul–Sep)", "Q4 (Oct–Dec)"]
            colors_q = [C_TEAL, C_PURPLE, C_INDIGO, C_ORANGE]
            c1, c2 = st.columns(2)
            for ax, y_col, title, ytitle in [
                (c1, "avg_count",  "Avg Transaction Count by Quarter", "Avg Count (K)"),
                (c2, "avg_amount", "Avg Transaction Amount by Quarter", "Avg Amount (₹M)")
            ]:
                scale = 1e3 if "count" in y_col else 1e6
                fig = px.bar(x=q_labels, y=df_seas[y_col]/scale, title=title,
                    color=q_labels, color_discrete_sequence=colors_q,
                    labels={"x": "Quarter", "y": ytitle},
                    text=(df_seas[y_col]/scale).apply(lambda x: f"{x:.0f}"))
                fig.update_traces(textposition="outside", textfont_size=11,
                    marker=dict(line=dict(width=0)))
                fig.update_layout(**layout(
                    showlegend=False,
                    height=370,
                    yaxis=dict(title=ytitle, gridcolor=C_BORDER, color=C_MUTED),
                    xaxis=dict(gridcolor="rgba(0,0,0,0)", color=C_MUTED),
                ))
                ax.plotly_chart(fig, use_container_width=True)
            insight("Q4 peaks every year — Diwali + Dussehra + year-end spending. Pre-emptive capacity scaling from September is operationally critical.")

    with tab3:
        if df_agg_txn.empty:
            st.warning("No transaction data available.")
        else:
            fig = go.Figure()
            box_colors = [C_PURPLE, C_INDIGO, C_PINK, C_GREEN, C_ORANGE]
            for i, typ in enumerate(df_agg_txn["transaction_type"].unique()):
                data = df_agg_txn[df_agg_txn["transaction_type"] == typ]["transaction_amount"].values
                fig.add_trace(go.Box(
                    y=data, name=typ,
                    marker_color=box_colors[i % len(box_colors)],
                    line=dict(color=box_colors[i % len(box_colors)]),
                    fillcolor=f"rgba({int(box_colors[i%len(box_colors)][1:3],16)},{int(box_colors[i%len(box_colors)][3:5],16)},{int(box_colors[i%len(box_colors)][5:7],16)},0.15)",
                    boxmean="sd",
                    opacity=0.9,
                    hovertemplate=f"<b>{typ}</b><br>%{{y:,.0f}}<extra></extra>"
                ))
            fig.update_yaxes(type="log", title="Transaction Amount (₹, log scale)", gridcolor=C_BORDER, color=C_MUTED)
            fig.update_layout(**layout(
                title="Transaction Amount Distribution by Type — Box Plot (log scale)",
                height=470,
                xaxis=dict(gridcolor="rgba(0,0,0,0)", color=C_MUTED),
            ))
            st.plotly_chart(fig, use_container_width=True)
            insight("Financial Services = widest IQR and highest outliers. Per-type fraud detection thresholds significantly reduce false positives.")


# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("<hr>", unsafe_allow_html=True)
st.markdown(f"""
<div style="display:flex; justify-content:space-between; align-items:center; padding:6px 0 16px;">
  <div style="font-size:12px; color:{C_MUTED}; font-family:'JetBrains Mono',monospace;">
    PhonePe Transaction Insights · EDA Dashboard
  </div>
  <div style="font-size:12px; color:{C_MUTED};">
    Data: <a href="https://github.com/PhonePe/pulse" style="color:{C_ACCENT}; text-decoration:none; font-weight:500;">PhonePe Pulse GitHub ↗</a>
  </div>
</div>
""", unsafe_allow_html=True)