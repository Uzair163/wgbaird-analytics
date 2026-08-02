"""
W&G Baird — Customer Value, Risk & Reorder Intelligence
Streamlit dashboard (Python/pandas equivalent of the Power BI report)

Run locally:      streamlit run app.py
Run online:       deploy this repo on share.streamlit.io (see README)

Reads the seven CSVs produced by pipeline.py. Re-run the pipeline, then
refresh the browser tab — no dashboard code changes needed for new data.
"""

from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

INK = "#1B2A41"
ACCENT = "#7A1F2B"
GREY = "#D8DCE3"
BODY = "#3B4453"

OUTPUT_DIR = Path("output")

st.set_page_config(page_title="W&G Baird — Customer Analytics", layout="wide")


# ---------------------------------------------------------------
# Data loading (cached so switching pages/filters doesn't re-read CSVs)
# ---------------------------------------------------------------
@st.cache_data
def load_data():
    d = {}
    d["customer_value"] = pd.read_csv(OUTPUT_DIR / "customer_value_and_churn.csv")
    d["concentration"] = pd.read_csv(OUTPUT_DIR / "customer_concentration.csv")
    d["reorder_windows"] = pd.read_csv(OUTPUT_DIR / "reorder_windows.csv", parse_dates=["last_order", "predicted_next_order"])
    d["delivery_time"] = pd.read_csv(OUTPUT_DIR / "delivery_time_by_work_type.csv")
    d["work_type_va"] = pd.read_csv(OUTPUT_DIR / "work_type_margin.csv")
    d["product_type_va"] = pd.read_csv(OUTPUT_DIR / "product_type_margin.csv")
    d["new_vs_retained"] = pd.read_csv(OUTPUT_DIR / "new_vs_retained.csv")
    return d


try:
    data = load_data()
except FileNotFoundError:
    st.error(
        "No output CSVs found. Run `python pipeline.py` first (with your data "
        "in `data/input/`), then reload this page."
    )
    st.stop()

customer_value = data["customer_value"]
concentration = data["concentration"]
reorder_windows = data["reorder_windows"]
delivery_time = data["delivery_time"]
work_type_va = data["work_type_va"]
product_type_va = data["product_type_va"]
new_vs_retained = data["new_vs_retained"]


# ---------------------------------------------------------------
# Sidebar — global filters. Because the whole script reruns on any
# widget change, these filter EVERY page automatically. This is the
# one thing that's simpler here than in the Power BI version, which
# needed relationships + synced slicers to get the same behaviour.
# ---------------------------------------------------------------
st.sidebar.title("W&G Baird")
st.sidebar.caption("Customer value, risk & reorder intelligence")

page = st.sidebar.radio(
    "Page",
    ["Overview", "At-Risk Customers", "Reorder Timelines", "Margin & Product Mix", "Operations"],
)

st.sidebar.markdown("---")
st.sidebar.subheader("Filters (apply to every page)")

all_customers = sorted(customer_value["customer_name"].dropna().unique())
selected_customers = st.sidebar.multiselect("Customer", all_customers, default=[])

all_work_types = sorted(work_type_va["work_type"].dropna().unique())
selected_work_types = st.sidebar.multiselect("Work type", all_work_types, default=[])

# Apply filters (empty selection = no filter, matches Power BI slicer default)
cv = customer_value.copy()
conc = concentration.copy()
rw = reorder_windows.copy()
if selected_customers:
    cv = cv[cv["customer_name"].isin(selected_customers)]
    conc = conc[conc["customer_name"].isin(selected_customers)]
    rw = rw[rw["customer_name"].isin(selected_customers)]

wt_va = work_type_va.copy()
dt = delivery_time.copy()
if selected_work_types:
    wt_va = wt_va[wt_va["work_type"].isin(selected_work_types)]
    dt = dt[dt["work_type"].isin(selected_work_types)]
# Note: reorder_windows and customer_value have no work_type column (they're
# customer-grain, not job-grain), so the work-type filter only applies to
# the Margin & Product Mix and Operations pages — same limitation noted in
# the README under "future development" (star-schema / job-level fact table).


# ---------------------------------------------------------------
# Page: Overview
# ---------------------------------------------------------------
if page == "Overview":
    st.title("Overview")

    total_customers = len(cv)
    total_va = cv["total_va_gbp_equiv"].sum()
    at_risk_va = cv.loc[cv["at_risk"], "total_va_gbp_equiv"].sum()
    at_risk_pct = (at_risk_va / total_va * 100) if total_va else 0

    c1, c2, c3 = st.columns(3)
    c1.metric("Total customers", f"{total_customers}")
    c2.metric("Total value added (GBP-equiv)", f"£{total_va:,.0f}")
    c3.metric("At-risk value (k=1)", f"£{at_risk_va:,.0f}", f"{at_risk_pct:.1f}% of total")

    st.markdown("#### Cumulative share of total value-added, customers ranked highest first")
    fig = px.line(conc.sort_values("customer_rank"), x="customer_rank", y="cume_pct")
    fig.update_traces(line_color=INK, line_width=3)
    fig.add_hline(y=80, line_dash="dash", line_color=GREY)
    fig.update_layout(yaxis_title="Cumulative % of VA", xaxis_title="Customer rank",
                       yaxis_range=[0, 100], plot_bgcolor="white")
    st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------
# Page: At-Risk Customers
# ---------------------------------------------------------------
elif page == "At-Risk Customers":
    st.title("At-risk customers")

    threshold_choice = st.radio(
        "Threshold", ["Standard (k=1)", "Stricter (k=1.5)"], horizontal=True
    )
    flag_col = "at_risk" if threshold_choice.startswith("Standard") else "at_risk_1_5sd"

    at_risk_df = cv[cv[flag_col]].sort_values("total_va_gbp_equiv", ascending=False)

    n = len(at_risk_df)
    va = at_risk_df["total_va_gbp_equiv"].sum()
    st.markdown(f"**{n} customers** flagged, holding **£{va:,.0f}** of value added.")

    show_cols = [
        "customer_name", "total_va_gbp_equiv", "days_since_last",
        "mean_gap", "sd_gap_filled", "churn_threshold", "n_orders",
    ]
    st.dataframe(
        at_risk_df[show_cols].rename(columns={
            "customer_name": "Customer", "total_va_gbp_equiv": "Value added (GBP-equiv)",
            "days_since_last": "Days since last order", "mean_gap": "Normal gap (days)",
            "sd_gap_filled": "Gap variability (SD, days)", "churn_threshold": "Flag threshold (days)",
            "n_orders": "Total orders",
        }),
        use_container_width=True, hide_index=True,
    )

    st.caption(
        "\u201cAt risk\u201d means a customer has gone quieter than their own normal ordering "
        "pattern, not quieter than a fixed number of days that applies to everyone."
    )


# ---------------------------------------------------------------
# Page: Reorder Timelines
# ---------------------------------------------------------------
elif page == "Reorder Timelines":
    st.title("Reorder timelines")
    st.markdown(
        f"**{rw['customer_id'].nunique()} of {len(customer_value)} customers** "
        "have at least one recurring job with enough history to predict a next-order date."
    )

    soon = rw.sort_values("predicted_next_order").copy()
    soon["predicted_next_order"] = soon["predicted_next_order"].dt.date
    soon["last_order"] = soon["last_order"].dt.date

    show_cols = ["customer_name", "title", "n_orders", "mean_gap", "last_order", "predicted_next_order"]
    st.dataframe(
        soon[show_cols].rename(columns={
            "customer_name": "Customer", "title": "Job / title", "n_orders": "Past orders",
            "mean_gap": "Average gap (days)", "last_order": "Last order",
            "predicted_next_order": "Predicted next order",
        }),
        use_container_width=True, hide_index=True,
    )
    st.caption("Sorted soonest first — a ready-made outreach list, not a delivery commitment.")


# ---------------------------------------------------------------
# Page: Margin & Product Mix
# ---------------------------------------------------------------
elif page == "Margin & Product Mix":
    st.title("Margin & product mix")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### Mean VA% by work type")
        wt_sorted = wt_va.sort_values("mean_va_pct", ascending=False)
        fig = px.bar(wt_sorted, x="work_type", y="mean_va_pct", text_auto=".0%")
        fig.update_traces(marker_color=INK)
        fig.update_layout(yaxis_tickformat=".0%", yaxis_title="Mean VA%", xaxis_title=None, plot_bgcolor="white")
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.markdown("#### Top 15 product types by total value added")
        top_products = product_type_va.sort_values("total_va", ascending=False).head(15)
        fig2 = px.bar(top_products, x="total_va", y="product_type_clean", orientation="h")
        fig2.update_traces(marker_color=ACCENT)
        fig2.update_layout(yaxis_title=None, xaxis_title="Total value added (GBP)",
                            plot_bgcolor="white", yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig2, use_container_width=True)


# ---------------------------------------------------------------
# Page: Operations
# ---------------------------------------------------------------
elif page == "Operations":
    st.title("Operations")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### Median delivery time by work type")
        dt_sorted = dt.sort_values("median_days_to_ship", ascending=False)
        fig = px.bar(dt_sorted, x="work_type", y="median_days_to_ship", text_auto=True)
        fig.update_traces(marker_color=INK)
        fig.update_layout(yaxis_title="Median days to ship", xaxis_title=None, plot_bgcolor="white")
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Excludes rows flagged as date anomalies (ship date logged before order date).")

    with col2:
        st.markdown("#### New vs retained customers by year")
        fig2 = px.bar(
            new_vs_retained, x="order_year", y="n_customers", color="customer_status",
            barmode="stack", color_discrete_map={"New": ACCENT, "Retained": GREY},
        )
        fig2.update_layout(xaxis_title="Year", yaxis_title="Customers", plot_bgcolor="white", legend_title=None)
        st.plotly_chart(fig2, use_container_width=True)
        st.caption("2023 is the first year in the data extract, so every active customer that year shows as \u2018New\u2019 by construction.")
