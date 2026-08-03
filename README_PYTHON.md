# W&G Baird Commercial Analytics

An analytical pipeline and live dashboard that turns raw sales transaction exports into
board-ready insight on customer value, churn risk, reorder timing and margin.
Python/pandas/Streamlit for the QUB KTP recruitment task.

**Author:** Uzair Khan
**Stack:** Python (pandas, matplotlib) → CSV → Streamlit

---

## 1. Business problem

W&G Baird holds detailed transaction-level sales data but no systematic, repeatable way
to answer three commercial questions from it:

1. Which customers and work types actually drive value, and how concentrated is that value?
2. Which customers have gone quiet compared to their own normal ordering pattern, and how
   much revenue is that risk attached to?
3. For recurring jobs, when is a customer likely to reorder, so sales can follow up
   proactively rather than reactively?

This pipeline answers all three, and keeps answering them every time a new data extract
lands, not just for the one sample file used to build it.

## 2. Architecture

```
data/input/*.xlsx  --(Pipeline.ipynb)-->  output/*.csv + output/charts/*.png  --(app.py)-->  live Streamlit dashboard
```

- **Pipeline.ipynb** loads every `.xlsx` in `data/input/`, validates its columns against the
  "Field Definitions" tab of the workbook (a schema change fails loudly instead of
  silently producing wrong numbers), cleans known data-quality issues, and writes seven
  summary CSVs plus three chart PNGs.
- **app.py** is a Streamlit app that reads those CSVs and presents them across five
  pages: Overview, At-Risk Customers, Reorder Timelines, Margin & Product Mix, and
  Operations.
- A sidebar filter (customer, work type) applies across every page at once, because
  Streamlit reruns the whole script on any interaction. That replaces what needed
  relationships and synced slicers to achieve in the Power BI version.

## 3. Repository structure

```
├── Pipeline.ipynb                         # load → clean → validate → summarise → write CSVs + charts
├── app.py                              # Streamlit dashboard, 5 pages
├── requirements.txt
├── data/input/                         # drop new .xlsx exports here, same sheet structure
├── output/
│   ├── customer_value_and_churn.csv    # 1 row per customer: value, cadence, at-risk flags
│   ├── customer_concentration.csv      # customers ranked by value, cumulative % of total VA
│   ├── reorder_windows.csv             # 1 row per (customer, recurring job): predicted next order date
│   ├── delivery_time_by_work_type.csv  # order-to-ship time by work type
│   ├── work_type_margin.csv            # VA% by work type
│   ├── product_type_margin.csv         # VA% and value by product type
│   ├── new_vs_retained.csv             # new vs retained customer counts by year
│   ├── revenue_forecast_6m.csv         # monthly revenue: actual, model fit, 6-month forecast + error band
│   └── charts/                         # PNG exports of the headline charts
```

## 4. Running it

**Locally:**
```
pip install -r requirements.txt
python Pipeline.ipynb          # place your .xlsx in data/input/ first
streamlit run app.py
```

**Online, no install** (see step-by-step below): deploy on Streamlit Community Cloud
for a live shareable link, and use Google Colab to rerun the pipeline against new data
without installing anything locally.

### Deploying the dashboard live
1. Push this repo to GitHub.
2. Go to [share.streamlit.io](https://share.streamlit.io), sign in with GitHub, click
   **New app**.
3. Select the repo, branch `main`, main file path `app.py`, click **Deploy**.
4. You get a live URL in about a minute. It rebuilds automatically whenever you push a
   change or new CSVs to the repo.

### Reproducing a refresh, online
1. Open [colab.research.google.com](https://colab.research.google.com), new notebook.
2. Upload `Pipeline.ipynb` and a new `.xlsx` into a `data/input/` folder in the Colab file
   browser.
3. `!pip install pandas openpyxl matplotlib -q`
4. `!python Pipeline.ipynb`
5. Download the refreshed `output/` folder, commit it to the repo, and the live
   Streamlit app picks up the new numbers on next load.

## 5. Headline insights (from the sample dataset provided)

| Insight | Finding |
|---|---|
| Customer concentration | The top **30 of 50 customers (60%)** account for 80% of total value-added, not a classic 20/80 split |
| Churn risk | **15 of 50 customers (30%)** are flagged at-risk on the standard threshold, representing **~32% of total value-added (≈£4.1m GBP-equivalent)** |
| Margin by work type | **Wide Format (61%) and Litho (53%)** carry meaningfully stronger average VA% than Digital (37%) and Outwork (27%) |
| Reorder coverage | 29 of 50 customers (58%) have at least one recurring job with enough order history (≥3 orders) to support a predicted next-order date |
| Delivery time | Litho jobs take a median of 25 days to ship, roughly 4x longer than Digital (6 days) |
| 6-month revenue outlook | Next six months projected at roughly **£5.0m**, backtested error band of **±22%**, using a linear trend plus calendar-month seasonality, not machine learning |

Every one of these numbers was checked against the original R/Power BI build before
this port was handed over. They match exactly.

## 6. Data quality notes

The dataset needed a few practical fixes and clarifications before any analysis felt trustworthy.

One fully duplicate row—same job, same credit line, logged twice—was removed.
A total of 218 rows carried #DIV/0! in VA% or Mup% because the sell price sat at zero. Those rows stayed in the data; the VA amount still carries meaning, only the ratio does not. The problematic ratios were set to NA rather than dropped outright.

Nine rows showed a ship date earlier than the order date, which cannot happen in reality. Those rows stayed in the dataset but were excluded from any delivery-time calculations so they don’t distort timing metrics.

The “Binding Type” field looked sparse at first glance, with blanks on 41.6% of rows, but the field definitions treat that blank as a valid category—outsourced or not applicable—rather than missing data. Those entries were relabelled to reflect that meaning instead of being left as null.

“Product Type” arrived with 64 raw values. After trimming whitespace and merging two known near-duplicate labels (brochures and leaflets), that count dropped to 59. A few near-duplicates and misspellings remain and will need a proper mapping table later.

Each customer trades in a single currency, but not all customers share the same one. Some trade in Sterling, others in Euro. Any ranking or total that compares customers uses a GBP-equivalent column, while the native-currency totals stay alongside it for reference rather than being overwritten.

## 7. Known limitations

The extract starts in 2023, which means every customer active that year ends up tagged as “New” by definition. That label reflects the data window, not genuine acquisition. For any discussion about growth, the sensible starting point sits in 2024 onwards.

Reorder dates come from a straightforward average gap between past orders, not from a full forecasting model. That level of simplicity suits a sales follow-up prompt—“roughly when to call”—rather than a delivery promise.

The at-risk flag follows a clear rule: days since last order compared with a customer’s own historical average gap, plus a sensitivity multiple of that customer’s standard deviation. A very regular, high-frequency customer can trigger the flag after a short quiet spell. That behaviour is deliberate and documented, not a mistake.

Sidebar filters apply across customer and work type, but two tables—reorder_windows and customer_value—sit at customer level rather than job level. They carry no work-type column, so a work-type filter does not narrow those pages. Fixing that properly means moving to a single job-level fact table, described below.

The six-month revenue outlook carries a backtested error of about ±22%, which feels wide at first glance. Monthly revenue in this data jumps around; one large job can double a month. A narrow band would mislead. The current forecast works as a directional planning number, not a target to hit.

## 8. Future development

A natural next step involves shifting to a job-level fact table. Instead of exporting seven separately aggregated CSVs, the cleaned transaction-level data would feed one central table. The current views—customer value, reorder windows, risk flags—would then become filtered slices over that table. That change would remove the work-type filter limitation and open up richer filtering generally.

The EUR-to-GBP conversion rate should move from a hardcoded static value to a live source, so cross-currency rankings stay aligned with reality rather than drifting over time.

Refreshes can move from manual runs to a scheduled job. A simple option would be a GitHub Actions workflow that reruns Pipeline.ipynb on a timer or when new files land, keeping the dashboard current without someone pressing a button.

Finally, adding unit tests with pytest around the churn threshold and reorder-window logic would guard against silent regressions. Any future change to the pipeline would then have to pass those checks before it could reintroduce a calculation error.
