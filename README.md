# 📱 PhonePe Transaction Insights

**Domain:** Finance / Digital Payment Systems  
**Project Type:** EDA (Exploratory Data Analysis)  
**Data Source:** [PhonePe Pulse GitHub Repository](https://github.com/PhonePe/pulse)  
**Skills:** Python · SQLite · ETL · Data Visualization · Streamlit

---

## 📁 Project Structure

```
phonepe_insights/
│
├── src/
│   ├── etl.py           ← ETL: Clone repo → Parse 9 JSON tables → Load SQLite DB
│   └── analysis.py      ← EDA: Generate all 15 charts → Save to outputs/
│
├── dashboard/
│   └── app.py           ← Interactive Streamlit dashboard (6 pages, 15+ charts)
│
├── data/                ← Auto-created by etl.py
│   ├── pulse/           ← Cloned PhonePe Pulse GitHub repo (~500MB)
│   └── phonepe_pulse.db ← SQLite database (9 normalized tables)
│
├── outputs/             ← Auto-created by analysis.py
│   └── chart01_*.png … chart15_*.png
│
├── notebooks/           ← Place your original Kaggle .ipynb here for reference
│
├── requirements.txt
└── README.md
```

---

## ⚡ Quick Start (3 Steps)

### Step 1 — Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 2 — Run ETL Pipeline

> ⚠️ Requires internet. Downloads ~500MB from GitHub.

```bash
python src/etl.py
```

This will:
- Clone `https://github.com/PhonePe/pulse.git` into `data/pulse/`
- Parse all 9 JSON table types
- Load everything into `data/phonepe_pulse.db` (SQLite)

Expected output:
```
✅ aggregated_transaction           →   94,500 rows
✅ aggregated_user                  →  180,000 rows
✅ aggregated_insurance             →   12,600 rows
✅ map_transaction                  →  420,000 rows
✅ map_user                         →  380,000 rows
...
✅ SQLite DB ready: data/phonepe_pulse.db
```

### Step 3a — Run EDA Analysis (15 Static Charts)

```bash
python src/analysis.py
```

Charts are saved as PNG files in `outputs/`.

### Step 3b — Launch Interactive Dashboard

```bash
streamlit run dashboard/app.py
```

Opens at **http://localhost:8501** — no internet needed after ETL step.

---

## 📊 The 15 EDA Charts

| # | Chart | Type | Key Insight |
|---|-------|------|-------------|
| 1 | Top 10 States by Transaction Amount | Bar | MH, KA, TS dominate |
| 2 | Payment Category Distribution | Pie × 2 | P2P = ~45% count, ~50% value |
| 3 | Quarterly Transaction Growth | Dual-axis Line | COVID surge 2020–21 |
| 4 | State × Year Heatmap | Heatmap | MH compounds fastest |
| 5 | Type × Quarter Stacked | Stacked Bar | Merchant share growing |
| 6 | Device Brand Distribution | Bar + Pie | Xiaomi + Samsung = 38% |
| 7 | Insurance Growth | Dual-axis Line+Bar | Post-2020 surge |
| 8 | Registered vs App Opens Scatter | Scatter + Trend | Low-engagement outliers |
| 9 | YoY Growth Rate | Grouped Bar | Amount > Count growth |
| 10 | Top 15 States by Users | Horiz Bar | Wide geographic spread |
| 11 | Amount Distribution Box Plot | Log Box | Financial Services widest |
| 12 | Seasonality Analysis | Side-by-side Bar | Q4 festive peak |
| 13 | Top Districts/Pincodes | Horiz Bar | Metro districts dominate |
| 14 | Correlation Heatmap | Triangular Heatmap | Engagement = independent dim |
| 15 | Pair Plot — Key Variables | Pair Plot | 3 state tiers clearly separable |

---

## 🗄️ Database Schema (9 Tables)

| Table | Key Columns | Granularity |
|-------|-------------|-------------|
| `aggregated_transaction` | state, year, quarter, transaction_type, count, amount | State |
| `aggregated_user` | state, year, quarter, brand, brand_count, registered_users, app_opens | State × Brand |
| `aggregated_insurance` | state, year, quarter, insurance_type, count, amount | State |
| `map_transaction` | state, year, quarter, district, count, amount | District |
| `map_user` | state, year, quarter, district, registered_users, app_opens | District |
| `map_insurance` | state, year, quarter, district, count, amount | District |
| `top_transaction` | state, year, quarter, pincode, count, amount | Pincode |
| `top_user` | state, year, quarter, district, registered_users | District (Top) |
| `top_insurance` | state, year, quarter, pincode, count, amount | Pincode |

---

## 🎛️ Streamlit Dashboard Pages

| Page | Contents |
|------|----------|
| 🏠 Overview | KPI metrics, table summary, key findings |
| 📊 Transactions | Top states bar, type pie, quarterly trend, stacked stack |
| 👤 Users & Devices | Brand bar+pie, engagement by state, scatter |
| 🗺️ Geographic | Top districts, top pincodes |
| 🛡️ Insurance | Growth trend, top states by premium |
| 📈 Growth & Trends | YoY growth, seasonality, box plot |

---

## 💡 Key Business Findings

1. **Geographic Conversion** — High-registration, low-transaction states (UP, Bihar) → "First Transaction Incentive"
2. **Merchant Ecosystem** — Launch super-app layer (GST filing, loyalty tools) for stickiness
3. **Insurance Cross-Sell** — Context-based recommendations (travel after flight booking, etc.)
4. **Q4 Planning** — 2–3× capacity scaling from September for Diwali peak
5. **Re-Engagement** — Personalized push + gamification for the ~40% dormant registered users
6. **Financial Services** — Simplified SIP/FD onboarding; growing per-transaction value signals trust

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| Data Source | PhonePe Pulse GitHub (JSON) |
| ETL | Python + GitPython |
| Storage | SQLite (via `sqlite3`) |
| Analysis | pandas + NumPy |
| Static Visualization | Matplotlib + Seaborn |
| Interactive Dashboard | Streamlit + Plotly |

---

## 📌 Notes

- The PhonePe Pulse dataset covers **2018–2023** (24 quarters).
- All amounts are in **raw INR**; charts convert to millions/billions/trillions for readability.
- The dashboard re-uses the SQLite DB if already present — no re-cloning needed.
- If you get `ModuleNotFoundError: gitpython`, run `pip install gitpython`.
