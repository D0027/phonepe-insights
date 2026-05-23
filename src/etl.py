"""
PhonePe Transaction Insights — ETL Pipeline
============================================
Clones PhonePe Pulse GitHub repo → parses 9 JSON table types → loads into SQLite DB.
Run this ONCE before running analysis.py or the Streamlit dashboard.
"""

import os, json, sqlite3, subprocess, sys, warnings
import pandas as pd
from pathlib import Path

warnings.filterwarnings("ignore")

# ── Config ────────────────────────────────────────────────────────────────────
REPO_URL   = "https://github.com/PhonePe/pulse.git"
BASE_DIR   = Path(__file__).resolve().parent.parent
CLONE_PATH = BASE_DIR / "data" / "pulse"
DB_PATH    = BASE_DIR / "data" / "phonepe_pulse.db"


# ── Helpers ───────────────────────────────────────────────────────────────────
def clean_state(s: str) -> str:
    """andhra-pradesh → Andhra Pradesh"""
    return s.replace("-", " ").title()


def _state_path(data_path, *parts):
    """Try standard path, then fallback without 'country'."""
    p1 = os.path.join(data_path, *parts, "country", "india", "state")
    p2 = os.path.join(data_path, *parts, "india", "state")
    return p1 if os.path.exists(p1) else (p2 if os.path.exists(p2) else None)


def _iter_state_files(base):
    """Yield (state, year, quarter, filepath) for every JSON under base."""
    if not base:
        return
    for state in os.listdir(base):
        sp = os.path.join(base, state)
        if not os.path.isdir(sp):
            continue
        for year in os.listdir(sp):
            yp = os.path.join(sp, year)
            if not os.path.isdir(yp):
                continue
            for fname in os.listdir(yp):
                if fname.endswith(".json"):
                    yield (
                        clean_state(state),
                        int(year),
                        int(fname.replace(".json", "")),
                        os.path.join(yp, fname),
                    )


# ── 9 JSON Parsers ────────────────────────────────────────────────────────────

def parse_aggregated_transaction(dp):
    base, rows = _state_path(dp, "aggregated", "transaction"), []
    for state, year, q, fp in _iter_state_files(base):
        with open(fp) as f:
            d = json.load(f)
        for item in (d.get("data") or {}).get("transactionData", []):
            pi = item.get("paymentInstruments", [{}])[0]
            rows.append({
                "state": state, "year": year, "quarter": q,
                "transaction_type":   item.get("name", ""),
                "transaction_count":  pi.get("count", 0),
                "transaction_amount": pi.get("amount", 0),
            })
    return pd.DataFrame(rows)


def parse_aggregated_user(dp):
    base, rows = _state_path(dp, "aggregated", "user"), []
    for state, year, q, fp in _iter_state_files(base):
        with open(fp) as f:
            d = json.load(f)
        agg   = (d.get("data") or {}).get("aggregated", {})
        reg   = agg.get("registeredUsers", 0)
        opens = agg.get("appOpens", 0)
        for bi in ((d.get("data") or {}).get("usersByDevice") or []):
            rows.append({
                "state": state, "year": year, "quarter": q,
                "brand":             bi.get("brand", "Others"),
                "brand_count":       bi.get("count", 0),
                "brand_percentage":  bi.get("percentage", 0),
                "registered_users":  reg,
                "app_opens":         opens,
            })
    return pd.DataFrame(rows)


def parse_aggregated_insurance(dp):
    base, rows = _state_path(dp, "aggregated", "insurance"), []
    for state, year, q, fp in _iter_state_files(base):
        with open(fp) as f:
            d = json.load(f)
        for item in (d.get("data") or {}).get("transactionData", []):
            pi = item.get("paymentInstruments", [{}])[0]
            rows.append({
                "state": state, "year": year, "quarter": q,
                "insurance_type":   item.get("name", ""),
                "insurance_count":  pi.get("count", 0),
                "insurance_amount": pi.get("amount", 0),
            })
    return pd.DataFrame(rows)


def parse_map_transaction(dp):
    base, rows = _state_path(dp, "map", "transaction", "hover"), []
    for state, year, q, fp in _iter_state_files(base):
        with open(fp) as f:
            d = json.load(f)
        for item in (d.get("data") or {}).get("hoverDataList", []):
            m = item.get("metric") or [{}]
            rows.append({
                "state": state, "year": year, "quarter": q,
                "district":           item.get("name", "").replace("-", " ").title(),
                "transaction_count":  m[0].get("count", 0) if m else 0,
                "transaction_amount": m[0].get("amount", 0) if m else 0,
            })
    return pd.DataFrame(rows)


def parse_map_user(dp):
    base, rows = _state_path(dp, "map", "user", "hover"), []
    for state, year, q, fp in _iter_state_files(base):
        with open(fp) as f:
            d = json.load(f)
        hover = (d.get("data") or {}).get("hoverData") or {}
        for dist, vals in hover.items():
            rows.append({
                "state": state, "year": year, "quarter": q,
                "district":         dist.replace("-", " ").title(),
                "registered_users": vals.get("registeredUsers", 0),
                "app_opens":        vals.get("appOpens", 0),
            })
    return pd.DataFrame(rows)


def parse_map_insurance(dp):
    base, rows = _state_path(dp, "map", "insurance", "hover"), []
    for state, year, q, fp in _iter_state_files(base):
        with open(fp) as f:
            d = json.load(f)
        for item in (d.get("data") or {}).get("hoverDataList", []):
            m = item.get("metric") or [{}]
            rows.append({
                "state": state, "year": year, "quarter": q,
                "district":        item.get("name", "").replace("-", " ").title(),
                "insurance_count":  m[0].get("count", 0) if m else 0,
                "insurance_amount": m[0].get("amount", 0) if m else 0,
            })
    return pd.DataFrame(rows)


def parse_top_transaction(dp):
    base, rows = _state_path(dp, "top", "transaction"), []
    for state, year, q, fp in _iter_state_files(base):
        with open(fp) as f:
            d = json.load(f)
        for item in (d.get("data") or {}).get("pincodes", []):
            m = item.get("metric", {})
            rows.append({
                "state": state, "year": year, "quarter": q,
                "pincode":            item.get("entityName", ""),
                "transaction_count":  m.get("count", 0),
                "transaction_amount": m.get("amount", 0),
            })
    return pd.DataFrame(rows)


def parse_top_user(dp):
    base, rows = _state_path(dp, "top", "user"), []
    for state, year, q, fp in _iter_state_files(base):
        with open(fp) as f:
            d = json.load(f)
        for item in (d.get("data") or {}).get("districts", []):
            rows.append({
                "state": state, "year": year, "quarter": q,
                "district":         item.get("name", "").replace("-", " ").title(),
                "registered_users": item.get("registeredUsers", 0),
            })
    return pd.DataFrame(rows)


def parse_top_insurance(dp):
    base, rows = _state_path(dp, "top", "insurance"), []
    for state, year, q, fp in _iter_state_files(base):
        with open(fp) as f:
            d = json.load(f)
        for item in (d.get("data") or {}).get("pincodes", []):
            m = item.get("metric", {})
            rows.append({
                "state": state, "year": year, "quarter": q,
                "pincode":         item.get("entityName", ""),
                "insurance_count":  m.get("count", 0),
                "insurance_amount": m.get("amount", 0),
            })
    return pd.DataFrame(rows)


# ── ETL Runner ────────────────────────────────────────────────────────────────
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


def clone_repo():
    """Clone PhonePe Pulse if not already present.
    FIX: Auto-installs gitpython if missing (was a crash in original).
    """
    try:
        from git import Repo
    except ImportError:
        print("⏳ gitpython not found — installing now...")
        subprocess.run([sys.executable, "-m", "pip", "install", "gitpython", "-q"], check=True)
        from git import Repo  # retry after install

    if not CLONE_PATH.exists():
        print(f"⏳ Cloning PhonePe Pulse repository (~1-2 min) → {CLONE_PATH}")
        Repo.clone_from(REPO_URL, str(CLONE_PATH))
        print("✅ Cloned successfully!")
    else:
        print("✅ Repository already present — skipping clone.")
    return str(CLONE_PATH / "data")


def run_etl(data_path: str) -> dict:
    """Parse all JSON files and load into SQLite. Returns dict of DataFrames."""
    print("\n⏳ Parsing JSON files and loading into database...\n")
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn      = sqlite3.connect(str(DB_PATH))
    table_map = {}

    for table_name, parser_fn in PARSERS:
        try:
            df = parser_fn(data_path)
            if not df.empty:
                df.to_sql(table_name, conn, if_exists="replace", index=False)
                table_map[table_name] = df
                print(f"  ✅ {table_name:<30} → {len(df):>8,} rows")
            else:
                print(f"  ⚠️  {table_name:<30} → empty (not in this repo version)")
                table_map[table_name] = pd.DataFrame()
        except Exception as e:
            print(f"  ❌ {table_name:<30} → Error: {e}")
            table_map[table_name] = pd.DataFrame()

    conn.close()
    print(f"\n✅ SQLite DB ready: {DB_PATH}")
    return table_map


if __name__ == "__main__":
    data_path = clone_repo()
    run_etl(data_path)