# W&G Baird analytics — Python version

Same pipeline and dashboard as the R + Power BI version, ported to pandas
and Streamlit. See the main project README for the business context; this
file only covers what's different about running the Python version.

## Files
- `pipeline.py` — loads, cleans, validates and summarises the data, then
  writes 7 CSVs to `output/` and 3 chart PNGs to `output/charts/`.
- `app.py` — Streamlit dashboard reading those CSVs, five pages, with a
  sidebar filter that applies across every page at once.
- `requirements.txt` — everything needed to run both.
- `output/` — a pre-generated set of CSVs and charts from the sample data,
  included so the dashboard works immediately without running the pipeline
  first.

## Run it
```
pip install -r requirements.txt
python pipeline.py          # place your .xlsx in data/input/ first
streamlit run app.py
```
