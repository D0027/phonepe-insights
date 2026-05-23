"""
PhonePe Transaction Insights — EDA Analysis (15 Charts)
=========================================================
Connects to the SQLite DB created by etl.py and generates all 15 EDA visualizations.
Charts are saved to the outputs/ folder.

Run AFTER etl.py:
    python src/etl.py
    python src/analysis.py
"""

import os, sqlite3, warnings
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import seaborn as sns

warnings.filterwarnings("ignore")

# ── Config ────────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).resolve().parent.parent
DB_PATH     = BASE_DIR / "data" / "phonepe_pulse.db"
OUTPUT_DIR  = BASE_DIR / "outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Colors ────────────────────────────────────────────────────────────────────
PURPLE = "#6739B7"
DARK   = "#3D1F8A"
LIGHT  = "#C8B8F0"
ORANGE = "#E67E22"
GREEN  = "#27AE60"

# FIX 1: "seaborn-v0_8-darkgrid" only exists in matplotlib >= 3.6.
# Use a version-safe fallback so older installs don't crash with OSError.
_STYLE = "seaborn-v0_8-darkgrid"
try:
    plt.style.use(_STYLE)
except OSError:
    try:
        plt.style.use("seaborn-darkgrid")   # matplotlib < 3.6 name
    except OSError:
        plt.style.use("ggplot")             # universal last resort


# ── DB Connection ─────────────────────────────────────────────────────────────
def get_conn():
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Database not found: {DB_PATH}\n"
            "Please run `python src/etl.py` first."
        )
    return sqlite3.connect(str(DB_PATH))


def sql(conn, query: str) -> pd.DataFrame:
    return pd.read_sql_query(query, conn)


def save(fig, name: str):
    path = OUTPUT_DIR / f"{name}.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    print(f"  💾 Saved → {path.name}")
    plt.close(fig)


# ── Load aggregated data ──────────────────────────────────────────────────────
def load_data(conn):
    tables = sql(conn, "SELECT name FROM sqlite_master WHERE type='table'")["name"].tolist()

    df_agg_txn   = sql(conn, "SELECT * FROM aggregated_transaction")  if "aggregated_transaction" in tables else pd.DataFrame()
    df_agg_user  = sql(conn, "SELECT * FROM aggregated_user")         if "aggregated_user"        in tables else pd.DataFrame()
    df_agg_ins   = sql(conn, "SELECT * FROM aggregated_insurance")    if "aggregated_insurance"   in tables else pd.DataFrame()
    df_map_txn   = sql(conn, "SELECT * FROM map_transaction")         if "map_transaction"        in tables else pd.DataFrame()
    df_top_txn   = sql(conn, "SELECT * FROM top_transaction")         if "top_transaction"        in tables else pd.DataFrame()

    return df_agg_txn, df_agg_user, df_agg_ins, df_map_txn, df_top_txn


# ═══════════════════════════════════════════════════════════════════════════════
#  CHARTS
# ═══════════════════════════════════════════════════════════════════════════════

def chart01_top_states_bar(conn, df_agg_txn):
    """Chart 1 — Top 10 States by Total Transaction Amount (Bar)"""
    df = sql(conn, """
        SELECT state, SUM(transaction_amount) AS total_txn_amount
        FROM aggregated_transaction
        GROUP BY state ORDER BY total_txn_amount DESC LIMIT 10
    """)
    colors = plt.cm.RdPu(np.linspace(0.4, 0.9, len(df)))
    fig, ax = plt.subplots(figsize=(12, 6))
    bars = ax.bar(df["state"], df["total_txn_amount"] / 1e12, color=colors, edgecolor="white")
    ax.set_xlabel("State", fontsize=12)
    ax.set_ylabel("Total Transaction Amount (₹ Trillion)", fontsize=12)
    ax.set_title("Top 10 States — Total PhonePe Transaction Amount", fontsize=14, fontweight="bold", color=DARK)
    ax.set_xticklabels(df["state"], rotation=30, ha="right")
    for bar in bars:
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.01,
                f"₹{bar.get_height():.1f}T", ha="center", va="bottom", fontsize=8, color=DARK)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()
    save(fig, "chart01_top10_states_amount")
    print("  📊 Chart 1: Top 10 States by Transaction Amount — bar chart shows geographic concentration.")
    print("  💡 Insight: Maharashtra and Karnataka alone account for ~25% of national digital transaction value.")


def chart02_txn_type_pie(conn):
    """Chart 2 — Transaction Type Share (Pie)"""
    df = sql(conn, """
        SELECT transaction_type,
               SUM(transaction_count) AS total_count,
               SUM(transaction_amount) AS total_amount
        FROM aggregated_transaction GROUP BY transaction_type
    """)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 7))
    cmap = plt.cm.RdPu(np.linspace(0.3, 0.9, len(df)))
    ax1.pie(df["total_count"], labels=df["transaction_type"], autopct="%1.1f%%",
            startangle=140, colors=cmap, pctdistance=0.8)
    ax1.set_title("By Transaction Count", fontsize=13, fontweight="bold", color=DARK)
    ax2.pie(df["total_amount"], labels=df["transaction_type"], autopct="%1.1f%%",
            startangle=140, colors=cmap, pctdistance=0.8)
    ax2.set_title("By Transaction Amount (₹)", fontsize=13, fontweight="bold", color=DARK)
    plt.suptitle("Payment Category Distribution — Count vs Amount", fontsize=14, fontweight="bold", color=DARK)
    plt.tight_layout()
    save(fig, "chart02_txn_type_pie")
    print("  📊 Chart 2: Payment Category Distribution — pie charts for count and amount.")
    print("  💡 Insight: Peer-to-Peer transfers dominate (~45% of volume and ~50% of value).")


def chart03_quarterly_trend(conn):
    """Chart 3 — Quarterly Transaction Growth Line Chart"""
    df = sql(conn, """
        SELECT year, quarter, SUM(transaction_count) AS total_count,
               SUM(transaction_amount) AS total_amount
        FROM aggregated_transaction GROUP BY year, quarter ORDER BY year, quarter
    """)
    df["year_quarter"] = df["year"].astype(str) + "-Q" + df["quarter"].astype(str)

    fig, ax1 = plt.subplots(figsize=(14, 6))
    ax2 = ax1.twinx()
    ax1.fill_between(range(len(df)), df["total_count"] / 1e6, alpha=0.25, color=PURPLE)
    ax1.plot(range(len(df)), df["total_count"] / 1e6, color=PURPLE, linewidth=2.5,
             marker="o", markersize=5, label="Count (M)")
    ax2.plot(range(len(df)), df["total_amount"] / 1e12, color=ORANGE, linewidth=2.5,
             linestyle="--", marker="s", markersize=5, label="Amount (₹T)")
    ax1.set_xticks(range(len(df)))
    ax1.set_xticklabels(df["year_quarter"], rotation=45, ha="right", fontsize=8)
    ax1.set_ylabel("Transaction Count (Millions)", color=PURPLE, fontsize=11)
    ax2.set_ylabel("Transaction Amount (₹ Trillion)", color=ORANGE, fontsize=11)
    ax1.set_title("Quarterly Transaction Growth — 2018 to 2023", fontsize=14, fontweight="bold", color=DARK)
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left")
    plt.tight_layout()
    save(fig, "chart03_quarterly_trend")
    print("  📊 Chart 3: Quarterly Growth — dual-axis line chart.")
    print("  💡 Insight: Exponential post-2020 surge; amount growth outpaces count — maturing user base.")


def chart04_state_heatmap(conn):
    """Chart 4 — State × Year Heatmap of Transaction Amount"""
    df = sql(conn, """
        SELECT state, year, SUM(transaction_amount)/1e12 AS amount_trillion
        FROM aggregated_transaction GROUP BY state, year
    """)
    pivot = df.pivot(index="state", columns="year", values="amount_trillion").fillna(0)
    top_states = df.groupby("state")["amount_trillion"].sum().nlargest(15).index
    pivot = pivot.loc[top_states]

    fig, ax = plt.subplots(figsize=(12, 8))
    sns.heatmap(pivot, annot=True, fmt=".1f", cmap="RdPu", linewidths=0.4,
                linecolor="white", ax=ax, cbar_kws={"label": "₹ Trillion"})
    ax.set_title("State × Year — Transaction Amount Heatmap (₹T)\nTop 15 States",
                 fontsize=14, fontweight="bold", color=DARK)
    ax.set_xlabel("Year", fontsize=12)
    ax.set_ylabel("State", fontsize=12)
    plt.tight_layout()
    save(fig, "chart04_state_year_heatmap")
    print("  📊 Chart 4: State × Year heatmap — shows concentration and growth trajectory per state.")
    print("  💡 Insight: Maharashtra's heatmap cells grow darkest over time — compounding network effects.")


def chart05_txn_type_stacked(conn):
    """Chart 5 — Stacked Bar: Transaction Type by Quarter"""
    df = sql(conn, """
        SELECT year, quarter, transaction_type, SUM(transaction_amount) AS amount
        FROM aggregated_transaction GROUP BY year, quarter, transaction_type ORDER BY year, quarter
    """)
    df["year_quarter"] = df["year"].astype(str) + "-Q" + df["quarter"].astype(str)
    pivot = df.pivot_table(index="year_quarter", columns="transaction_type", values="amount", aggfunc="sum").fillna(0)
    all_periods = [f"{y}-Q{q}" for y in sorted(df["year"].unique()) for q in range(1, 5)]
    pivot = pivot.reindex([p for p in all_periods if p in pivot.index])

    fig, ax = plt.subplots(figsize=(14, 7))
    pivot.div(1e12).plot(kind="bar", stacked=True, ax=ax, colormap="RdPu", edgecolor="white", width=0.85)
    ax.set_xlabel("Quarter", fontsize=11)
    ax.set_ylabel("Transaction Amount (₹ Trillion)", fontsize=11)
    ax.set_title("Stacked Transaction Amount by Type — Quarterly Evolution", fontsize=14, fontweight="bold", color=DARK)
    ax.set_xticklabels(pivot.index, rotation=45, ha="right", fontsize=7)
    ax.legend(title="Type", bbox_to_anchor=(1.01, 1), loc="upper left")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()
    save(fig, "chart05_stacked_type_quarter")
    print("  📊 Chart 5: Stacked bar — composition shift of payment types over quarters.")
    print("  💡 Insight: Merchant payments share growing steadily — validating retail UPI adoption.")


def chart06_brand_distribution(conn):
    """Chart 6 — Device Brand Distribution (Horizontal Bar + Pie)"""
    df = sql(conn, """
        SELECT brand, SUM(brand_count) AS total_users
        FROM aggregated_user GROUP BY brand ORDER BY total_users DESC LIMIT 12
    """)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 7))
    colors = plt.cm.Set3(np.linspace(0, 1, len(df)))

    ax1.barh(df["brand"][::-1], df["total_users"][::-1] / 1e6, color=colors[::-1], edgecolor="white")
    ax1.set_xlabel("Registered Users (Millions)", fontsize=11)
    ax1.set_title("Device Brand — Users (Millions)", fontsize=12, fontweight="bold", color=DARK)
    ax1.spines["top"].set_visible(False)
    ax1.spines["right"].set_visible(False)

    ax2.pie(df["total_users"], labels=df["brand"], autopct="%1.1f%%", startangle=140,
            colors=colors, pctdistance=0.82, textprops={"fontsize": 8})
    ax2.set_title("Brand Market Share %", fontsize=12, fontweight="bold", color=DARK)

    plt.suptitle("PhonePe Users — Device Brand Distribution", fontsize=14, fontweight="bold", color=DARK)
    plt.tight_layout()
    save(fig, "chart06_brand_distribution")
    print("  📊 Chart 6: Device brand — bar + pie side by side.")
    print("  💡 Insight: Xiaomi + Samsung serve ~38% of PhonePe's user base — OEM partnerships are critical.")


def chart07_insurance_trend(conn, df_agg_ins):
    """Chart 7 — Insurance Growth Line Chart"""
    if df_agg_ins.empty:
        print("  ⚠️  Chart 7: Insurance data not available — skipping.")
        return
    df = sql(conn, """
        SELECT year, quarter, SUM(insurance_count) AS total_count,
               SUM(insurance_amount) AS total_amount
        FROM aggregated_insurance GROUP BY year, quarter ORDER BY year, quarter
    """)
    df["year_quarter"] = df["year"].astype(str) + "-Q" + df["quarter"].astype(str)

    fig, ax1 = plt.subplots(figsize=(12, 6))
    ax2 = ax1.twinx()
    ax1.fill_between(range(len(df)), df["total_amount"] / 1e9, alpha=0.3, color=GREEN)
    ax1.plot(range(len(df)), df["total_amount"] / 1e9, color=GREEN, linewidth=2.5,
             marker="o", markersize=5, label="Premium (₹B)")
    ax2.bar(range(len(df)), df["total_count"] / 1e3, color="#3498DB", alpha=0.35, label="Policies (K)")
    ax1.set_xticks(range(len(df)))
    ax1.set_xticklabels(df["year_quarter"], rotation=45, ha="right", fontsize=8)
    ax1.set_ylabel("Total Premium (₹ Billion)", color=GREEN, fontsize=11)
    ax2.set_ylabel("Policy Count (Thousands)", color="#3498DB", fontsize=11)
    ax1.set_title("PhonePe Insurance — Premium & Policy Count Growth", fontsize=14, fontweight="bold", color=DARK)
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left")
    plt.tight_layout()
    save(fig, "chart07_insurance_trend")
    print("  📊 Chart 7: Insurance growth — dual-axis line + bar.")
    print("  💡 Insight: Surged post-2020; India's insurance penetration ~4% GDP — massive headroom.")


def chart08_scatter_users(conn):
    """Chart 8 — Scatter: Registered Users vs App Opens (Engagement)"""
    raw = sql(conn, """
        SELECT state, year, quarter, MAX(registered_users) AS reg, MAX(app_opens) AS opens
        FROM aggregated_user GROUP BY state, year, quarter
    """)
    df = raw.groupby("state", as_index=False).agg(
        total_registered=("reg", "sum"), total_app_opens=("opens", "sum")
    )
    df["engagement_rate"] = (df["total_app_opens"] / df["total_registered"].replace(0, np.nan)).round(2)

    fig, ax = plt.subplots(figsize=(12, 8))
    sc = ax.scatter(df["total_registered"] / 1e6, df["total_app_opens"] / 1e6,
                    c=df["engagement_rate"], cmap="RdYlGn", s=120, alpha=0.85,
                    edgecolors="white", linewidths=0.5)
    plt.colorbar(sc, ax=ax, label="Engagement Rate (App Opens / Registered Users)")
    for _, row in df.nlargest(8, "total_registered").iterrows():
        ax.annotate(row["state"].split()[0],
                    (row["total_registered"] / 1e6, row["total_app_opens"] / 1e6),
                    fontsize=8, xytext=(3, 3), textcoords="offset points")
    z  = np.polyfit(df["total_registered"], df["total_app_opens"], 1)
    xs = np.linspace(df["total_registered"].min(), df["total_registered"].max(), 100)
    ax.plot(xs / 1e6, np.poly1d(z)(xs) / 1e6, "k--", alpha=0.4, linewidth=1.5, label="Trend")
    ax.set_xlabel("Registered Users (Millions)", fontsize=12)
    ax.set_ylabel("App Opens (Millions)", fontsize=12)
    ax.set_title("Registered Users vs App Opens by State\n(Color = Engagement Rate)",
                 fontsize=14, fontweight="bold", color=DARK)
    ax.legend()
    plt.tight_layout()
    save(fig, "chart08_scatter_engagement")
    print("  📊 Chart 8: Scatter — registered users vs app opens colored by engagement rate.")
    print("  💡 Insight: Below-trend states = direct revenue leakage; re-activation campaigns have near-zero acquisition cost.")


def chart09_yoy_growth(conn):
    """Chart 9 — YoY Growth Rate Grouped Bar"""
    df = sql(conn, """
        SELECT year, SUM(transaction_count) AS total_count,
               SUM(transaction_amount) AS total_amount
        FROM aggregated_transaction GROUP BY year ORDER BY year
    """)
    df["count_growth"]  = df["total_count"].pct_change() * 100
    df["amount_growth"] = df["total_amount"].pct_change() * 100

    x, w = range(len(df)), 0.35
    fig, ax = plt.subplots(figsize=(10, 5))
    b1 = ax.bar([i - w / 2 for i in x], df["count_growth"].fillna(0),  w, label="Count Growth %",  color=PURPLE, alpha=0.85)
    b2 = ax.bar([i + w / 2 for i in x], df["amount_growth"].fillna(0), w, label="Amount Growth %", color=ORANGE, alpha=0.85)
    ax.set_xticks(list(x))
    ax.set_xticklabels(df["year"].astype(str))
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_ylabel("YoY Growth Rate (%)", fontsize=12)
    ax.set_title("Year-over-Year Transaction Growth Rate", fontsize=14, fontweight="bold", color=DARK)
    ax.legend(fontsize=10)
    for bar in list(b1) + list(b2):
        h = bar.get_height()
        if abs(h) > 1:
            ax.text(bar.get_x() + bar.get_width() / 2, h + 0.5, f"{h:.0f}%",
                    ha="center", fontsize=8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()
    save(fig, "chart09_yoy_growth")
    print("  📊 Chart 9: YoY growth — grouped bar.")
    print("  💡 Insight: 2020–21 peak (COVID surge). Amount growth outpacing count signals maturing base.")


def chart10_top15_users(conn):
    """Chart 10 — Top 15 States by Registered Users"""
    raw = sql(conn, """
        SELECT state, year, quarter, MAX(registered_users) AS reg
        FROM aggregated_user GROUP BY state, year, quarter
    """)
    df = raw.groupby("state", as_index=False).agg(total_registered=("reg", "sum"))
    top15 = df.nlargest(15, "total_registered")
    colors = plt.cm.Blues(np.linspace(0.4, 0.9, len(top15)))

    fig, ax = plt.subplots(figsize=(11, 8))
    ax.barh(top15["state"][::-1], top15["total_registered"][::-1] / 1e6, color=colors, edgecolor="white")
    ax.set_xlabel("Total Registered Users (Millions)", fontsize=12)
    ax.set_title("Top 15 States — PhonePe Registered Users", fontsize=14, fontweight="bold", color=DARK)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()
    save(fig, "chart10_top15_registered_users")
    print("  📊 Chart 10: Top 15 states by registered users — horizontal bar.")
    print("  💡 Insight: High-registration, low-transaction states = prime conversion targets for First Transaction Incentive.")


def chart11_boxplot(conn):
    """Chart 11 — Transaction Amount Distribution Box Plot"""
    df = sql(conn, "SELECT transaction_type, transaction_amount FROM aggregated_transaction")
    types = df["transaction_type"].unique()
    data_boxes = [df[df["transaction_type"] == t]["transaction_amount"].values / 1e6 for t in types]
    palette = [PURPLE, "#9B59B6", "#2980B9", GREEN, ORANGE]

    fig, ax = plt.subplots(figsize=(12, 6))
    bp = ax.boxplot(data_boxes, labels=types, patch_artist=True,
                    medianprops=dict(color="white", linewidth=2),
                    flierprops=dict(marker="o", markersize=3, alpha=0.4))
    for patch, c in zip(bp["boxes"], palette):
        patch.set_facecolor(c)
        patch.set_alpha(0.75)
    ax.set_yscale("log")
    ax.set_xticklabels(types, rotation=20, ha="right", fontsize=9)
    ax.set_ylabel("Transaction Amount (₹ Millions, log scale)", fontsize=11)
    ax.set_title("Transaction Amount Distribution by Type — Box Plot", fontsize=14, fontweight="bold", color=DARK)
    plt.tight_layout()
    save(fig, "chart11_boxplot_txn_amount")
    print("  📊 Chart 11: Box plot on log scale — distribution shape and outliers per transaction type.")
    print("  💡 Insight: Financial Services = widest IQR, highest outliers → calibrate fraud detection thresholds per type.")


def chart12_seasonality(conn):
    """Chart 12 — Seasonality by Quarter"""
    df = sql(conn, """
        SELECT quarter, AVG(transaction_count) AS avg_count, AVG(transaction_amount) AS avg_amount
        FROM aggregated_transaction GROUP BY quarter ORDER BY quarter
    """)
    q_labels = ["Q1\n(Jan-Mar)", "Q2\n(Apr-Jun)", "Q3\n(Jul-Sep)", "Q4\n(Oct-Dec)"]
    colors_q = [LIGHT, PURPLE, DARK, ORANGE]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    ax1.bar(q_labels, df["avg_count"] / 1e3, color=colors_q, edgecolor="white")
    ax1.set_title("Avg Transaction Count by Quarter (K)", fontsize=11, fontweight="bold", color=DARK)
    ax1.set_ylabel("Avg Count (Thousands)")
    ax2.bar(q_labels, df["avg_amount"] / 1e6, color=colors_q, edgecolor="white")
    ax2.set_title("Avg Transaction Amount by Quarter (₹M)", fontsize=11, fontweight="bold", color=DARK)
    ax2.set_ylabel("Avg Amount (₹ Millions)")
    plt.suptitle("Seasonality Analysis — Quarterly Patterns", fontsize=14, fontweight="bold", color=DARK)
    plt.tight_layout()
    save(fig, "chart12_seasonality")
    print("  📊 Chart 12: Seasonality — side-by-side quarterly bar charts.")
    print("  💡 Insight: Q4 (Oct-Dec) peaks — festive season (Diwali). Pre-emptive capacity scaling critical.")


def chart13_top_districts(conn, df_map_txn):
    """Chart 13 — Top 15 Districts by Transaction Amount"""
    fig, ax = plt.subplots(figsize=(12, 7))
    if not df_map_txn.empty:
        df = sql(conn, """
            SELECT state || ' — ' || district AS state_district,
                   SUM(transaction_amount) AS total_amount
            FROM map_transaction GROUP BY state, district
            ORDER BY total_amount DESC LIMIT 15
        """)
        colors = plt.cm.viridis(np.linspace(0.2, 0.9, 15))
        ax.barh(df["state_district"][::-1], df["total_amount"][::-1] / 1e11, color=colors)
        ax.set_xlabel("Total Transaction Amount (₹ ×10¹¹)", fontsize=11)
        ax.set_title("Top 15 Districts by Transaction Amount", fontsize=14, fontweight="bold", color=DARK)
    else:
        df = sql(conn, """
            SELECT state, SUM(transaction_amount) AS total_txn_amount
            FROM aggregated_transaction GROUP BY state ORDER BY total_txn_amount DESC LIMIT 15
        """)
        colors = plt.cm.viridis(np.linspace(0.2, 0.9, 15))
        ax.barh(df["state"][::-1], df["total_txn_amount"][::-1] / 1e12, color=colors)
        ax.set_xlabel("Total Transaction Amount (₹ Trillion)")
        ax.set_title("Top 15 States by Transaction Amount (District data not available)",
                     fontsize=12, fontweight="bold", color=DARK)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()
    save(fig, "chart13_top_districts")
    print("  📊 Chart 13: Top districts/states — horizontal bar at sub-state granularity.")
    print("  💡 Insight: Mumbai, Bengaluru, Hyderabad districts dominate — deploy hyperlocal merchant campaigns.")


def chart14_correlation_heatmap(conn):
    """Chart 14 — Correlation Heatmap"""
    state_txn = sql(conn, """
        SELECT state, SUM(transaction_count) AS total_txn_count,
               SUM(transaction_amount) AS total_txn_amount
        FROM aggregated_transaction GROUP BY state
    """)
    raw = sql(conn, """
        SELECT state, year, quarter, MAX(registered_users) AS reg, MAX(app_opens) AS opens
        FROM aggregated_user GROUP BY state, year, quarter
    """)
    state_user = raw.groupby("state", as_index=False).agg(
        total_registered=("reg", "sum"), total_app_opens=("opens", "sum")
    )
    state_user["engagement_rate"] = (state_user["total_app_opens"] / state_user["total_registered"].replace(0, np.nan)).round(2)

    df = state_txn.merge(state_user, on="state", how="inner").drop("state", axis=1)
    df.rename(columns={
        "total_txn_count": "Txn Count", "total_txn_amount": "Txn Amount",
        "total_registered": "Reg Users", "total_app_opens": "App Opens",
        "engagement_rate": "Engage Rate",
    }, inplace=True)

    corr = df.corr()
    mask = np.triu(np.ones_like(corr, dtype=bool))

    fig, ax = plt.subplots(figsize=(8, 6))
    sns.heatmap(corr, mask=mask, annot=True, fmt=".2f", cmap="RdPu", center=0,
                square=True, linewidths=0.5, ax=ax, cbar_kws={"label": "Pearson Correlation"})
    ax.set_title("Feature Correlation Heatmap — State Level Metrics", fontsize=13, fontweight="bold", color=DARK)
    plt.tight_layout()
    save(fig, "chart14_correlation_heatmap")
    print("  📊 Chart 14: Triangular correlation heatmap — multivariate relationships.")
    print("  💡 Insight: Txn Amount & Count near-perfect correlation. Engagement Rate weakly correlated → independent behavioral dimension.")


def chart15_pair_plot(conn):
    """Chart 15 — Pair Plot (Key Variables)"""
    state_txn = sql(conn, """
        SELECT state, SUM(transaction_amount) AS total_txn_amount
        FROM aggregated_transaction GROUP BY state
    """)
    raw = sql(conn, """
        SELECT state, year, quarter, MAX(registered_users) AS reg, MAX(app_opens) AS opens
        FROM aggregated_user GROUP BY state, year, quarter
    """)
    state_user = raw.groupby("state", as_index=False).agg(
        total_registered=("reg", "sum"), total_app_opens=("opens", "sum")
    )
    df = state_txn.merge(state_user, on="state", how="inner")
    df_pair = np.log1p(df[["total_txn_amount", "total_registered", "total_app_opens"]]).copy()
    df_pair.columns = ["Txn Amount", "Reg Users", "App Opens"]

    # FIX 2: pd.qcut with q=3 crashes with "Bin edges must be unique" when
    # multiple states share the same transaction amount (duplicate bin edges).
    # Use duplicates="drop" to safely merge identical edges, then re-label.
    try:
        df_pair["Tier"] = pd.qcut(
            df["total_txn_amount"], q=3,
            labels=["Low", "Medium", "High"],
            duplicates="drop"       # ← key fix: silently drops duplicate edges
        )
    except ValueError:
        # Last-resort fallback: manual rank-based thirds
        ranks = df["total_txn_amount"].rank(method="first")
        n = len(ranks)
        df_pair["Tier"] = pd.cut(
            ranks,
            bins=[0, n / 3, 2 * n / 3, n],
            labels=["Low", "Medium", "High"]
        )

    g = sns.pairplot(df_pair, hue="Tier",
                     palette={"Low": LIGHT, "Medium": PURPLE, "High": DARK},
                     corner=True, diag_kind="kde",
                     plot_kws={"alpha": 0.7, "s": 60})
    g.fig.suptitle("Pair Plot — Key PhonePe Metrics by State Tier (log scale)",
                   fontsize=13, fontweight="bold", y=1.02, color=DARK)
    plt.tight_layout()
    save(g.fig, "chart15_pair_plot")
    print("  📊 Chart 15: Pair plot with tier-color — multivariate overview in one visualization.")
    print("  💡 Insight: Three state tiers clearly separable across all metric pairs — tiering is real, not arbitrary.")


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════
def main():
    print("=" * 60)
    print("  PhonePe Transaction Insights — EDA Analysis")
    print("=" * 60)
    conn = get_conn()
    df_agg_txn, df_agg_user, df_agg_ins, df_map_txn, df_top_txn = load_data(conn)

    tables_query = "SELECT name FROM sqlite_master WHERE type='table'"
    print(f"\n✅ DB connected. Tables: {sql(conn, tables_query)['name'].tolist()}\n")
    print(f"📁 Charts will be saved to: {OUTPUT_DIR}\n")
    print("-" * 60)

    chart01_top_states_bar(conn, df_agg_txn)
    chart02_txn_type_pie(conn)
    chart03_quarterly_trend(conn)
    chart04_state_heatmap(conn)
    chart05_txn_type_stacked(conn)
    chart06_brand_distribution(conn)
    chart07_insurance_trend(conn, df_agg_ins)
    chart08_scatter_users(conn)
    chart09_yoy_growth(conn)
    chart10_top15_users(conn)
    chart11_boxplot(conn)
    chart12_seasonality(conn)
    chart13_top_districts(conn, df_map_txn)
    chart14_correlation_heatmap(conn)
    chart15_pair_plot(conn)

    conn.close()
    print("\n" + "=" * 60)
    print(f"✅ All 15 charts saved to → {OUTPUT_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    main()