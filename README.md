# Systems Thinking Analysis Portal

A reusable local web application for uploading CSVs, previewing and validating data, running supported cross-impact analysis, inspecting numeric summaries/plots, and downloading a genuine Excel workbook.

## Important academic limitation

The course-specific formulas and workflow for **Kane's Simulation** were not included with the initial request. This version intentionally does not invent or run a substitute. Upload the relevant course notes/example before implementing that module. The influence/dependence measures currently use row sums and column sums, with median-based descriptive groups; confirm these conventions with your course materials.

## Requirements

- Python 3.10 or newer
- Internet access during first-time dependency installation (or install packages from a local wheel cache)
- A modern browser

## Install and run

### Windows
1. Extract the ZIP to a folder.
2. Install Python 3.10+ and make sure `python` is available in Command Prompt.
3. Double-click `start_portal.bat` or run these commands in the folder:

```bat
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

4. Streamlit will show a local URL, normally `http://localhost:8501`. Open it in your browser.
5. Keep the terminal window open while using the app. To stop the server, press `Ctrl+C`. To reopen later, activate `.venv` and run `python -m streamlit run app.py`.

### macOS / Linux
```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

## CSV patterns

- General tabular CSV: preview, validation, numeric summaries, and row-order plots.
- Square cross-impact matrix: first column contains row factor names; remaining column headers contain the same factor names. Values must be numeric.
- Long-form relationships: use the mapping panel to select source, target, and impact columns. Each directed source-target pair must be unique, numeric, and collectively form a complete square factor set. Missing links are not assumed to be zero.

## Multiple files and data isolation

You can upload multiple CSVs together and choose which one to analyse. Each report is generated for the currently selected file; data from other uploaded files is not merged. Upload additional files in later sessions without changing source code. This initial version does not persist projects/history after the browser session or server restarts; save exported workbooks to retain results.

## Excel export

The button downloads a real `.xlsx` workbook containing Original Data, Cleaned Data, Data Validation, Parameters and Assumptions, plus any applicable Cross-Impact Matrix, Influence Dependence, Numeric Summary, and Executive Summary sheets. It omits worksheets for methods that were not run. Workbook styling includes frozen headers and filters.

## Limits and privacy

- Local availability depends on the computer running the server and its resources. This is not 24/7 cloud hosting.
- No arbitrary usage counter is implemented. Practical limits depend on RAM, browser performance, and file size.
- Files are processed by the local app process; this project does not include a cloud database, user accounts, or saved project history.
- This app does not impute missing values or invent causal links or cross-impact scores.
