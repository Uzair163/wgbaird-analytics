"""
W&G Baird — Customer Value, Reorder & Churn Analysis Pipeline (Python port)
Author: Uzair Khan | QUB KTP recruitment task

Same reproducible-pipeline design as the original R version: modular
functions, no hardcoded values, safe to re-run against a new data drop
with no code changes. See run_pipeline() at the bottom.

Run it with:  python pipeline.py
"""

import re
from pathlib import Path

import numpy as np
import pandas as pd

# ---- Config ---------------------------------------------------
INPUT_DIR = Path("data/input")     # drop any new export here, same column structure
OUTPUT_DIR = Path("output")
CHART_DIR = OUTPUT_DIR / "charts"  # PNG exports for the README / slide deck
CHURN_K = 1                        # number of SDs beyond a customer's own mean
                                    # order gap before they're flagged "at risk"
MIN_ORDERS_FOR_REORDER_WINDOW = 3  # need >=3 orders on one Title to trust a cadence

# EUR -> GBP conversion, used ONLY for blended cross-currency ranking/totals.
# Every customer trades in a single currency (checked: 0 of 50 mix), so
# per-customer native totals are always correct; this rate exists purely so
# customers can be ranked/summed against each other on one scale for the
# board view. Update to a current rate before presenting, and always keep
# the native-currency figures alongside the converted ones, never replace.
EUR_TO_GBP = 0.86

INPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Known naming drift: the Field Definitions tab lists "Rep Name", but the
# actual data column is "Rep". Checked directly against the sample file —
# aliased here so validation doesn't false-flag every run over this one
# cosmetic mismatch. Add further aliases here if future drops rename fields.
KNOWN_FIELD_ALIASES = {"Rep Name": "Rep"}

RENAME_MAP = {
    "Title": "title",
    "CustomerID": "customer_id",
    "Customer Name": "customer_name",
    "Job Status": "job_status",
    "SalesIn": "sales_in",
    "SalesOut": "sales_out",
    "Ship date": "ship_date",
    "Quantity": "quantity",
    "Sell Price": "sell_price",
    "Mup%": "mup_pct",
    "VA Amount": "va_amount",
    "VA/24": "va_per_hour",
    "VA%": "va_pct",
    "VA/K": "va_per_k",
    "Rebate": "rebate",
    "Puchases": "purchases",
    "Press hrs": "press_hrs",
    "Impressions": "impressions",
    "Handling": "handling",
    "Labour": "labour",
    "Paper": "paper",
    "Rep": "rep",
    "Region": "region",
    "Industry": "industry",
    "Work Type": "work_type",
    "Product Type": "product_type",
    "Binding Type": "binding_type",
    "Currency": "currency",
}


def _snake(name: str) -> str:
    """Fallback snake_case for any column not covered by RENAME_MAP
    (e.g. 'Year', 'Week No.') — equivalent to janitor::clean_names()."""
    name = re.sub(r"[^0-9a-zA-Z]+", "_", str(name)).strip("_")
    name = re.sub(r"(?<!^)(?=[A-Z])", "_", name)
    return name.lower()


# ============================================================
# 1. LOAD
# ============================================================
def get_expected_columns(reference_file: Path) -> list:
    """Read the Field Definitions tab and return the expected column names.
    This is the source of truth for what a new data drop should contain."""
    defs = pd.read_excel(reference_file, sheet_name="Field Definitions")
    names_raw = defs["Field Name"].dropna().tolist()
    return [KNOWN_FIELD_ALIASES.get(n, n) for n in names_raw]


def validate_columns(file_path: Path, expected_cols: list) -> bool:
    """Compare a new file's columns against the expected set. Prints exactly
    what's missing or unexpected, so a schema drift in a future data drop
    fails loudly instead of silently producing wrong numbers."""
    actual_cols = pd.read_excel(file_path, sheet_name="Master Plain (Anon)", nrows=0).columns.tolist()

    missing = sorted(set(expected_cols) - set(actual_cols))
    unexpected = sorted(set(actual_cols) - set(expected_cols))

    if missing:
        print(f"MISSING columns in {file_path.name}: {', '.join(missing)}")
    if unexpected:
        print(f"UNEXPECTED columns in {file_path.name}: {', '.join(unexpected)}")

    return len(missing) == 0  # only missing columns block ingestion; extra columns just warn


def load_raw_data(input_dir: Path = INPUT_DIR) -> pd.DataFrame:
    """Load and combine every .xlsx file sitting in input_dir.
    New data = drop another file with the same 'Master Plain (Anon)' sheet
    structure into data/input/ and re-run. No code changes."""
    files = sorted(input_dir.glob("*.xlsx"))
    if not files:
        raise FileNotFoundError(f"No .xlsx files found in {input_dir}")

    expected_cols = get_expected_columns(files[0])
    valid_files = [f for f in files if validate_columns(f, expected_cols)]
    if len(valid_files) < len(files):
        print(f"WARNING: {len(files) - len(valid_files)} file(s) skipped due to missing columns — see messages above.")

    frames = []
    for f in valid_files:
        d = pd.read_excel(f, sheet_name="Master Plain (Anon)")
        d["source_file"] = f.name
        frames.append(d)
    return pd.concat(frames, ignore_index=True)


# ============================================================
# 1.5 QUICK PROFILING / QA CHECKS
# ============================================================
def profile_data(raw: pd.DataFrame) -> None:
    """Independent re-run of the core profiling checks against the RAW data,
    before any cleaning is applied."""
    print("---- Null counts (top 10) ----")
    print(raw.isna().sum().sort_values(ascending=False).head(10))

    print("\n---- Fully identical duplicate rows ----")
    dup_mask = raw.duplicated(keep="first")
    dup_any = raw.duplicated(keep=False)
    print(f"{dup_mask.sum()} extra copies ( {dup_any.sum()} rows total involved )")

    print("\n---- Repeated Title values (legitimate reorders, not errors) ----")
    counts = raw["Title"].value_counts()
    repeated = counts[counts > 1]
    print(f"{repeated.sum()} rows across {len(repeated)} distinct Titles")

    print("\n---- #DIV/0! rows ----")
    print("VA%: ", (raw["VA%"] == "#DIV/0!").sum())
    print("Mup%:", (raw["Mup%"] == "#DIV/0!").sum())

    print("\n---- Ship date before SalesIn (impossible) ----")
    print(f"{(raw['Ship date'] < raw['SalesIn']).sum()} rows")


# ============================================================
# 2. CLEAN
# ============================================================
def clean_data(raw: pd.DataFrame) -> pd.DataFrame:
    """Standardise column names and fix the specific data quality issues
    identified during profiling. Nothing is silently dropped — problem
    rows are flagged, not deleted."""
    df = raw.rename(columns=RENAME_MAP)
    # any leftover raw column names (Year, Week No., etc.) get snake_cased
    df.columns = [c if c in RENAME_MAP.values() else _snake(c) for c in df.columns]

    # Issue 0: fully identical duplicate rows — a genuine duplicate, not a
    # repeat order. Drop the redundant copy. Must NOT be confused with
    # repeated `title` values elsewhere (those recur legitimately across
    # different dates) — drop_duplicates() only removes rows identical in
    # every single column, so the real reorder structure is untouched.
    n_before = len(df)
    df = df.drop_duplicates()
    print(f"Removed {n_before - len(df)} fully duplicate row(s).")

    # Issue 1: VA%/Mup% hold "#DIV/0!" text where Sell Price = 0 (goodwill /
    # zero-value jobs). Coerce to NaN rather than dropping the row — the VA
    # amount itself is still valid, only the ratio is undefined.
    df["va_pct"] = pd.to_numeric(df["va_pct"], errors="coerce")
    df["mup_pct"] = pd.to_numeric(df["mup_pct"], errors="coerce")
    df["zero_price_job_flag"] = df["sell_price"] == 0

    # Issue 2: blank Binding Type is a valid category per the field
    # definitions — it means outsourced / not applicable, not missing.
    df["binding_type"] = df["binding_type"].fillna("Outsourced/Not applicable")

    # Issue 3 & 6: convert to plain dates first (removes any ambiguity in
    # date arithmetic), then flag ship_date before sales_in as impossible.
    df["sales_in"] = pd.to_datetime(df["sales_in"]).dt.normalize()
    df["sales_out"] = pd.to_datetime(df["sales_out"]).dt.normalize()
    df["ship_date"] = pd.to_datetime(df["ship_date"]).dt.normalize()
    df["date_anomaly_flag"] = df["ship_date"].notna() & df["sales_in"].notna() & (df["ship_date"] < df["sales_in"])

    # Issue 4: negative VA amount / sell price = credits, reworks, goodwill
    # jobs. Real business activity — kept in, flagged for transparency.
    df["credit_or_rework_flag"] = (df["va_amount"] < 0) | (df["sell_price"] < 0)

    # Issue 5: Product Type has ~64 distinct raw values, several of which
    # are the same category typed inconsistently. Squish whitespace and
    # fold the specific near-duplicates spotted in this sample into one
    # label. Add more mappings here if a new data drop introduces further
    # typo variants — this is a partial cleanup, not a comprehensive one.
    df["product_type_clean"] = df["product_type"].astype(str).str.strip().str.replace(r"\s+", " ", regex=True)
    lower = df["product_type_clean"].str.lower()
    df.loc[lower.str.contains("brochures", na=False), "product_type_clean"] = "Brochures / Price List"
    df.loc[lower.str.contains("leaflets to a4", na=False), "product_type_clean"] = "Leaflets to A4 / Price Lists"

    return df


# ============================================================
# 2.5 DATA VALIDATION ASSERTIONS
# ============================================================
def run_data_validation_checks(df: pd.DataFrame) -> None:
    """Systematic business-rule checks: state what's logically impossible
    for each field, then count violations. Doesn't alter the data."""
    print("---- Data validation assertions ----")
    print("Ship date before SalesIn (impossible):     ", df["date_anomaly_flag"].sum())
    print("Negative Quantity:                          ", (df["quantity"] < 0).sum())
    print("Negative Sell Price:                        ", (df["sell_price"] < 0).sum())
    print("Zero-price jobs (VA%/Mup% undefined):       ", df["zero_price_job_flag"].sum())
    print("Negative VA Amount / credit-or-rework rows: ", df["credit_or_rework_flag"].sum())
    print("SalesOut before SalesIn (impossible):       ", (df["sales_out"] < df["sales_in"]).sum())


# ============================================================
# 3. JOB-LEVEL REORDER HISTORY
# ============================================================
def build_job_history(df: pd.DataFrame) -> pd.DataFrame:
    """`title` is not a unique job ID — it's a recurring job/product code.
    Builds the gap-between-orders table the reorder prediction is based on."""
    jh = df[df["sales_in"].notna()].sort_values(["title", "sales_in"]).copy()
    jh["gap_days"] = jh.groupby("title")["sales_in"].diff().dt.days
    return jh


def summarise_reorder_windows(job_history: pd.DataFrame, min_orders: int = MIN_ORDERS_FOR_REORDER_WINDOW) -> pd.DataFrame:
    """Per-Title reorder statistics, restricted to Titles with enough
    history to trust a cadence estimate (>= 3 orders = 2+ gaps)."""
    grp = job_history.groupby(["title", "customer_id", "customer_name"])
    out = grp.agg(
        n_orders=("sales_in", "size"),
        mean_gap=("gap_days", "mean"),
        sd_gap=("gap_days", "std"),
        last_order=("sales_in", "max"),
    ).reset_index()
    out = out[out["n_orders"] >= min_orders].copy()
    out["predicted_next_order"] = out["last_order"] + pd.to_timedelta(out["mean_gap"].round(), unit="D")
    return out


# ============================================================
# 4. CUSTOMER-LEVEL CADENCE & CHURN
# ============================================================
def summarise_customer_cadence(df: pd.DataFrame, ref_date=None, k: float = CHURN_K) -> pd.DataFrame:
    """Order cadence per customer across ALL their orders (not just repeat
    Titles), so low-frequency customers still get a churn read."""
    if ref_date is None:
        ref_date = df["sales_in"].max()

    d = df[df["sales_in"].notna()].sort_values(["customer_id", "sales_in"]).copy()
    d["gap_days"] = d.groupby("customer_id")["sales_in"].diff().dt.days

    out = d.groupby("customer_id").agg(
        customer_name=("customer_name", "first"),
        n_orders=("sales_in", "size"),
        mean_gap=("gap_days", "mean"),
        sd_gap=("gap_days", "std"),
        first_order=("sales_in", "min"),
        last_order=("sales_in", "max"),
    ).reset_index()

    # Customers with only 1-2 orders won't have a reliable SD — fall back to
    # half the mean gap as a conservative estimate rather than dropping them.
    out["sd_gap_filled"] = out["sd_gap"].fillna(out["mean_gap"] * 0.5)
    out["days_since_last"] = (ref_date - out["last_order"]).dt.days

    # Sensitivity check: report the flag at both k=1 and a stricter k=1.5,
    # so "at risk" isn't a single arbitrary cutoff.
    out["churn_threshold"] = out["mean_gap"] + (k * out["sd_gap_filled"])
    out["at_risk"] = out["days_since_last"] > out["churn_threshold"]
    out["churn_threshold_1_5sd"] = out["mean_gap"] + (1.5 * out["sd_gap_filled"])
    out["at_risk_1_5sd"] = out["days_since_last"] > out["churn_threshold_1_5sd"]
    return out


def summarise_customer_value(df: pd.DataFrame, cadence: pd.DataFrame, eur_to_gbp: float = EUR_TO_GBP) -> pd.DataFrame:
    """Customer value (total VA, VA share, job count), joined onto cadence.

    IMPORTANT: every customer trades in a single currency, but customers
    differ from EACH OTHER in currency. Summing/ranking raw sell_price /
    va_amount across customers would silently blend Sterling and Euro as if
    equal. Keeps the native-currency total AND adds total_va_gbp_equiv,
    which is the only column that should be used for cross-customer
    ranking, sums, or a single headline number.
    """
    value = df.groupby(["customer_id", "currency"]).agg(
        total_va=("va_amount", "sum"),
        total_sell=("sell_price", "sum"),
        n_jobs=("va_amount", "size"),
    ).reset_index()

    value["total_va_gbp_equiv"] = np.where(
        value["currency"] == "Euro", value["total_va"] * eur_to_gbp, value["total_va"]
    )
    value["va_pct_of_total"] = value["total_va_gbp_equiv"] / value["total_va_gbp_equiv"].sum() * 100

    merged = cadence.merge(value, on="customer_id", how="left")
    return merged.sort_values(["at_risk", "total_va_gbp_equiv"], ascending=[False, False])


# ============================================================
# 5. SUPPORTING CUTS
# ============================================================
def summarise_work_type_margin(df: pd.DataFrame) -> pd.DataFrame:
    """VA% by Work Type — feeds the 'where should we invest' recommendation."""
    d = df[df["sell_price"] > 0]  # excludes the #DIV/0! rows cleanly
    out = d.groupby("work_type").agg(
        n_jobs=("va_amount", "size"),
        total_va=("va_amount", "sum"),
        mean_va_pct=("va_pct", "mean"),
    ).reset_index()
    return out.sort_values("total_va", ascending=False)


def summarise_product_type_margin(df: pd.DataFrame) -> pd.DataFrame:
    """VA% by cleaned Product Type — finer-grained than Work Type."""
    d = df[df["sell_price"] > 0]
    out = d.groupby("product_type_clean").agg(
        n_jobs=("va_amount", "size"),
        total_va=("va_amount", "sum"),
        mean_va_pct=("va_pct", "mean"),
    ).reset_index()
    return out.sort_values("total_va", ascending=False)


def summarise_customer_concentration(customer_value: pd.DataFrame) -> pd.DataFrame:
    """How many customers drive 80% of VA. Uses the GBP-equivalent total
    so the ranking isn't distorted by currency mixing."""
    out = customer_value.sort_values("total_va_gbp_equiv", ascending=False).copy()
    out["cume_va_gbp"] = out["total_va_gbp_equiv"].cumsum()
    out["cume_pct"] = out["cume_va_gbp"] / out["total_va_gbp_equiv"].sum() * 100
    out["customer_rank"] = range(1, len(out) + 1)
    return out[["customer_rank", "customer_id", "customer_name", "total_va_gbp_equiv", "cume_pct"]]


def summarise_delivery_time(df: pd.DataFrame) -> pd.DataFrame:
    """Delivery time (SalesIn -> Ship date), by Work Type. Excludes rows
    flagged as date anomalies so they don't distort the median/mean."""
    d = df[df["sales_in"].notna() & df["ship_date"].notna() & ~df["date_anomaly_flag"]].copy()
    d["days_to_ship"] = (d["ship_date"] - d["sales_in"]).dt.days
    out = d.groupby("work_type").agg(
        n_jobs=("days_to_ship", "size"),
        median_days_to_ship=("days_to_ship", "median"),
        mean_days_to_ship=("days_to_ship", "mean"),
    ).reset_index()
    return out.sort_values("median_days_to_ship", ascending=False)


def summarise_new_vs_retained(df: pd.DataFrame) -> pd.DataFrame:
    """New vs retained CUSTOMERS by year (counts distinct customers, not
    order rows — a customer with 40 orders in a year counts once).

    CAVEAT: 2023 is the first year in this extract, so every customer active
    that year is labelled 'New' by construction — treat that figure as a
    data-window artefact, not genuine acquisition, and lead with 2024
    onwards for real growth claims.
    """
    first_year = df.groupby("customer_id")["sales_in"].min().dt.year.rename("first_year")
    d = df.merge(first_year, on="customer_id", how="left")
    d["order_year"] = d["sales_in"].dt.year
    d["customer_status"] = np.where(d["order_year"] == d["first_year"], "New", "Retained")
    d = d[["customer_id", "order_year", "customer_status"]].drop_duplicates()
    return d.groupby(["order_year", "customer_status"]).size().reset_index(name="n_customers")


# ============================================================
# 6. CHART EXPORTS
# ============================================================
def generate_charts(customer_value: pd.DataFrame, work_type_va: pd.DataFrame,
                     concentration: pd.DataFrame, chart_dir: Path = CHART_DIR) -> None:
    """Same three visualisations shown in the board deck, generated straight
    from the pipeline output. Re-running the pipeline regenerates all three,
    so charts dropped into the README never drift out of sync with the data."""
    import matplotlib.pyplot as plt

    chart_dir.mkdir(parents=True, exist_ok=True)
    INK, ACCENT, GREY = "#1B2A41", "#7A1F2B", "#D8DCE3"
    plt.rcParams["font.size"] = 11

    # 1. Concentration curve
    fig, ax = plt.subplots(figsize=(7.5, 5))
    ax.plot(concentration["customer_rank"], concentration["cume_pct"], color=INK, linewidth=2.2)
    ax.axhline(80, linestyle="--", color=GREY)
    ax.set_ylim(0, 100)
    ax.set_xlabel("Customer rank")
    ax.set_ylabel("Cumulative % of VA")
    ax.set_title("Cumulative share of total value-added, customers ranked highest first", fontsize=10.5, color="#3B4453")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(chart_dir / "customer_concentration.png", dpi=200, facecolor="white")
    plt.close(fig)

    # 2. At-risk value, doughnut
    at_risk_va = customer_value.loc[customer_value["at_risk"], "total_va_gbp_equiv"].sum()
    rest_va = customer_value.loc[~customer_value["at_risk"], "total_va_gbp_equiv"].sum()
    fig, ax = plt.subplots(figsize=(5, 5))
    wedges, _, autotexts = ax.pie(
        [at_risk_va, rest_va], colors=[ACCENT, GREY], startangle=90,
        autopct="%.1f%%", pctdistance=0.8,
        wedgeprops=dict(width=0.4, edgecolor="white"),
    )
    for t in autotexts:
        t.set_color("white")
        t.set_fontweight("bold")
    ax.set_title("Value added, GBP-equivalent", fontsize=10.5, color="#3B4453")
    ax.legend(wedges, ["At-risk (k=1)", "Rest of book"], loc="lower center",
              bbox_to_anchor=(0.5, -0.08), ncol=2, frameon=False)
    fig.tight_layout()
    fig.savefig(chart_dir / "at_risk_share.png", dpi=200, facecolor="white")
    plt.close(fig)

    # 3. Mean VA% by work type
    wt = work_type_va.sort_values("mean_va_pct", ascending=False)
    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    bars = ax.bar(wt["work_type"], wt["mean_va_pct"] * 100, color=INK, width=0.6)
    ax.bar_label(bars, fmt="%.0f%%", padding=3)
    ax.set_ylabel("Mean VA%")
    ax.set_ylim(0, wt["mean_va_pct"].max() * 100 * 1.15)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(chart_dir / "margin_by_work_type.png", dpi=200, facecolor="white")
    plt.close(fig)

    print(f"Charts written to {chart_dir}: customer_concentration.png, at_risk_share.png, margin_by_work_type.png")


# ============================================================
# RUN PIPELINE
# ============================================================
def run_pipeline(input_dir: Path = INPUT_DIR, output_dir: Path = OUTPUT_DIR) -> dict:
    raw = load_raw_data(input_dir)

    print("\n============ RAW DATA PROFILE ============")
    profile_data(raw)

    df = clean_data(raw)

    print("\n============ POST-CLEAN VALIDATION ============")
    run_data_validation_checks(df)

    print(f"Rows loaded: {len(df)}")
    print(f"Div/0 rows (va_pct now NA): {(df['va_pct'].isna() & (df['sell_price'] == 0)).sum()}")
    print(f"Date anomalies flagged: {df['date_anomaly_flag'].sum()}")
    print(f"Credit/rework rows flagged: {df['credit_or_rework_flag'].sum()}")

    job_history = build_job_history(df)
    reorder_windows = summarise_reorder_windows(job_history)
    cadence = summarise_customer_cadence(df)
    customer_value = summarise_customer_value(df, cadence)
    concentration = summarise_customer_concentration(customer_value)
    delivery_time = summarise_delivery_time(df)
    work_type_va = summarise_work_type_margin(df)
    product_type_va = summarise_product_type_margin(df)
    new_vs_retained = summarise_new_vs_retained(df)

    covered_customers = reorder_windows["customer_id"].nunique()
    total_customers = df["customer_id"].nunique()

    output_dir.mkdir(parents=True, exist_ok=True)
    reorder_windows.to_csv(output_dir / "reorder_windows.csv", index=False)
    customer_value.to_csv(output_dir / "customer_value_and_churn.csv", index=False)
    concentration.to_csv(output_dir / "customer_concentration.csv", index=False)
    delivery_time.to_csv(output_dir / "delivery_time_by_work_type.csv", index=False)
    work_type_va.to_csv(output_dir / "work_type_margin.csv", index=False)
    product_type_va.to_csv(output_dir / "product_type_margin.csv", index=False)
    new_vs_retained.to_csv(output_dir / "new_vs_retained.csv", index=False)

    generate_charts(customer_value, work_type_va, concentration)

    at_risk_value = customer_value.loc[customer_value["at_risk"], "total_va_gbp_equiv"].sum()
    total_value = customer_value["total_va_gbp_equiv"].sum()
    print(
        f"At-risk customers (k=1): {customer_value['at_risk'].sum()} of {len(customer_value)} | "
        f"VA at risk: GBP-equiv {at_risk_value:,.0f} ({at_risk_value / total_value * 100:.1f}% of total)"
    )
    print(f"At-risk customers (stricter k=1.5): {customer_value['at_risk_1_5sd'].sum()} of {len(customer_value)}")
    print(
        f"Job-level reorder window coverage: {covered_customers} of {total_customers} customers "
        f"({covered_customers / total_customers * 100:.0f}%) have a Title with >={MIN_ORDERS_FOR_REORDER_WINDOW} orders"
    )

    return dict(
        df=df, reorder_windows=reorder_windows, customer_value=customer_value,
        concentration=concentration, delivery_time=delivery_time,
        work_type_va=work_type_va, product_type_va=product_type_va,
        new_vs_retained=new_vs_retained,
    )


if __name__ == "__main__":
    # Place the source .xlsx in data/input/ before running this.
    results = run_pipeline()

# ============================================================
# DEMONSTRATING DYNAMISM (for the video)
# ============================================================
# To prove the pipeline updates with new data, with no code changes:
#   1. Take a small batch of new orders in the same column structure
#      as the original file (e.g. copy a few rows, change dates/values).
#   2. Save as a second .xlsx into data/input/
#   3. Re-run:  python pipeline.py
#   4. Show that output/customer_value_and_churn.csv (and the Streamlit
#      dashboard built on top of it) has changed — no code was touched,
#      only the input folder contents.
