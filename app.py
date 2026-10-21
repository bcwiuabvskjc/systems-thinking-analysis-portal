from __future__ import annotations
from datetime import datetime
import io, os, re
import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st
from analysis_core import validate_dataframe, coerce_numeric, detect_cross_impact, cross_impact_metrics, build_excel

st.set_page_config(page_title="Systems Thinking Analysis Portal", page_icon="🧭", layout="wide")
st.markdown("""<style>
.block-container {padding-top: 1.5rem; padding-bottom: 3rem; max-width: 1500px;}
.hero {padding: 1.4rem 1.6rem; border-radius: 16px; background: linear-gradient(120deg,#12263a,#245b78); color: white; margin-bottom: 1rem;}
.hero h1 {color:white; margin:0;} .hero p {color:#e4edf4; margin:.45rem 0 0 0;}
.small-note {font-size: .9rem; color: #64748b;}
</style>
<div class="hero"><h1>Systems Thinking Analysis Portal</h1><p>Upload, validate, analyse, visualize, and export your project data — with transparent assumptions and independent processing for each dataset.</p></div>""", unsafe_allow_html=True)

with st.sidebar:
    st.header("Project workflow")
    st.markdown("1. Upload CSV\n2. Preview and validate\n3. Map relationship columns if needed\n4. Review analyses\n5. Download Excel report")
    st.divider()
    st.info("Each uploaded file is analysed independently. No values are imputed and no missing cross-impact scores are invented.")
    st.caption("Local app: availability depends on the computer/server running it.")

files = st.file_uploader("Upload one or more CSV files", type=["csv"], accept_multiple_files=True, help="You can upload a new file later without reinstalling or rebuilding the portal.")
if not files:
    st.markdown("### Get started")
    st.write("Upload a CSV to begin. The portal will preview your data, run basic validation, detect compatible analysis structures, and prepare a genuine Excel workbook.")
    st.warning("**Kane’s Simulation is not auto-run yet.** Its exact formulas and workflow must come from your course notes. Upload those notes or provide the required formulas before enabling this module.")
    st.markdown("#### Supported data patterns (initial version)")
    c1,c2,c3 = st.columns(3)
    c1.markdown("**General data**\n\nAny tabular CSV for preview, validation, and numeric summaries.")
    c2.markdown("**Cross-impact matrix**\n\nSquare matrix with factor names in the first column and matching factor names as column headers.")
    c3.markdown("**Relationship list**\n\nLong-form rows that can be mapped to source factor, target factor, and impact value.")
    st.stop()

# Per-file state is rebuilt from each file's bytes, avoiding cross-file data leakage.
file_labels = [f.name for f in files]
selected_name = st.selectbox("Choose the dataset to analyse", file_labels, key="selected_dataset")
file_obj = next(f for f in files if f.name == selected_name)
try:
    raw_bytes = file_obj.getvalue()
    try:
        original = pd.read_csv(io.BytesIO(raw_bytes), encoding="utf-8-sig")
    except UnicodeDecodeError:
        original = pd.read_csv(io.BytesIO(raw_bytes), encoding="latin-1")
except Exception as e:
    st.error(f"Could not read **{selected_name}** as a CSV: {e}. Check the delimiter, encoding, and file contents, then upload it again.")
    st.stop()

st.caption(f"Currently analysing: **{selected_name}** · {len(original):,} rows · {len(original.columns):,} columns")
if original.empty or len(original.columns) == 0:
    st.error("This CSV has no usable data rows or columns. Upload a valid CSV and try again.")
    st.stop()
cleaned = coerce_numeric(original)
validation = validate_dataframe(original)

# Optional mapping for long-form relationship data.
st.header("1 · Uploaded data")
with st.expander("Preview rows and columns", expanded=True):
    st.dataframe(original.head(100), use_container_width=True, height=300)
    st.caption(f"Showing up to 100 of {len(original):,} rows. Original uploaded values are preserved in the export.")

st.header("2 · Data validation")
err_count = int((validation["Severity"] == "Error").sum())
warn_count = int((validation["Severity"] == "Warning").sum())
a,b,c = st.columns(3)
a.metric("Rows", f"{len(original):,}")
b.metric("Columns", f"{len(original.columns):,}")
c.metric("Errors / warnings", f"{err_count} / {warn_count}")
st.dataframe(validation, use_container_width=True, hide_index=True)
if err_count:
    st.error("Resolve the structural errors before interpreting analysis results. The original data is still preserved.")

st.header("3 · Cross-Impact Matrix")
colnames = list(original.columns)
source_default = next((c for c in colnames if str(c).lower().strip() in ["source", "from", "cause", "factor_from", "event_from"]), colnames[0])
target_default = next((c for c in colnames if str(c).lower().strip() in ["target", "to", "effect", "factor_to", "event_to"]), colnames[min(1,len(colnames)-1)])
value_default = next((c for c in colnames if str(c).lower().strip() in ["impact", "influence", "weight", "score", "value", "effect_size"]), colnames[-1])
with st.expander("Relationship-column mapping (use this if your CSV is a list of relationships)"):
    st.write("Only map columns if each row represents a directed relationship. Duplicate source–target pairs and missing values are flagged rather than silently combined.")
    m1,m2,m3 = st.columns(3)
    source_col = m1.selectbox("Source factor column", colnames, index=colnames.index(source_default), key=f"src_{selected_name}")
    target_col = m2.selectbox("Target factor column", colnames, index=colnames.index(target_default), key=f"tgt_{selected_name}")
    value_col = m3.selectbox("Impact / score column", colnames, index=colnames.index(value_default), key=f"val_{selected_name}")

matrix, matrix_message = detect_cross_impact(original)
if matrix is None and len(set([source_col,target_col,value_col])) == 3:
    mapped_matrix, mapped_message = detect_cross_impact(original, source_col, target_col, value_col)
    if mapped_matrix is not None:
        matrix, matrix_message = mapped_matrix, mapped_message
    else:
        matrix_message = mapped_message if "Duplicate" in mapped_message or "missing" in mapped_message or "complete square" in mapped_message else matrix_message
st.caption(matrix_message)
metrics = None
if matrix is not None:
    st.markdown("**Detected matrix values** — review these before interpreting them. The app treats row sums as outgoing influence and column sums as incoming dependence; confirm this convention matches your course notes.")
    edited = st.data_editor(matrix, use_container_width=True, key=f"matrix_editor_{selected_name}")
    try:
        matrix = edited.apply(pd.to_numeric, errors="raise")
        if matrix.isna().any().any():
            st.error("Matrix contains missing values. Fill or correct them explicitly before analysis.")
            matrix = None
        else:
            metrics, metric_definitions = cross_impact_metrics(matrix)
            left,right = st.columns(2)
            with left:
                st.subheader("Cross-impact heatmap")
                fig = px.imshow(matrix, text_auto=True, aspect="auto", labels=dict(x="Target factor", y="Source factor", color="Impact"), title="Cross-Impact Matrix")
                st.plotly_chart(fig, use_container_width=True)
            with right:
                st.subheader("Influence and dependence")
                fig2 = px.scatter(metrics, x="Dependence (column sum)", y="Influence (row sum)", text="Factor", hover_data=["Median-based descriptive group"], title="Influence vs. Dependence")
                fig2.update_traces(textposition="top center")
                st.plotly_chart(fig2, use_container_width=True)
            st.dataframe(metrics, use_container_width=True, hide_index=True)
            with st.expander("Definitions and classification caveat"):
                st.dataframe(metric_definitions, hide_index=True, use_container_width=True)
                st.warning("The four groups use sample medians as a transparent descriptive default, not a claim about your professor’s classification rules. Replace this with the course method if it differs.")
    except Exception as e:
        st.error(f"Matrix analysis could not run: {e}. Check that all matrix cells are numeric.")
else:
    st.info("Cross-impact calculations are not available until the data forms a valid square matrix. No absent relationship is treated as zero.")

st.header("4 · Other data-supported analysis")
numeric = cleaned.select_dtypes(include=[np.number])
numeric_summary = pd.DataFrame()
if len(numeric.columns):
    numeric_summary = numeric.describe().T.reset_index().rename(columns={"index":"Variable"})
    st.subheader("Numeric summary")
    st.dataframe(numeric_summary, use_container_width=True, hide_index=True)
    chart_col = st.selectbox("Choose a numeric variable to inspect", list(numeric.columns), key=f"chart_var_{selected_name}")
    plot_df = cleaned[[chart_col]].copy().reset_index(names="Row")
    st.plotly_chart(px.line(plot_df, x="Row", y=chart_col, markers=True, title=f"Behaviour-over-rows: {chart_col}", labels={"Row":"Row index", chart_col:chart_col}), use_container_width=True)
    st.caption("This is a row-order plot, not a time-series model unless the row order and variable definitions support that interpretation.")
else:
    st.info("No numeric columns were detected for numeric summary or row-order plots.")

st.subheader("Methods requiring additional inputs or course definitions")
with st.expander("Kane’s Simulation — awaiting course methodology"):
    st.warning("Not calculated. The uploaded request requires course-specific formulas, and those notes are not included in this upload. Upload the relevant lecture notes/example or provide the formula, required input columns, update rules, stopping condition, and expected outputs. The app will not substitute a generic simulation.")
with st.expander("Causal loop diagrams, stock-and-flow, archetypes, scenarios and sensitivity"):
    st.write("These methods need explicit causal links, loop polarity, stocks/flows, archetype criteria, scenario assumptions, or parameter ranges. They are not inferred from ordinary tabular columns because that could invent causal relationships. Add these inputs or upload your course template to support these modules.")

st.header("5 · Export results")
params = pd.DataFrame([
    {"Parameter":"Input filename", "Value":selected_name, "Status":"User supplied"},
    {"Parameter":"Numeric conversion", "Value":"Only columns whose nonblank values all parse as numbers are converted", "Status":"Application rule"},
    {"Parameter":"Missing values", "Value":"Not imputed; reported in validation", "Status":"Application rule"},
    {"Parameter":"Cross-impact row sums", "Value":"Sum of each row", "Status":"Calculated if valid matrix" if matrix is not None else "Not run"},
    {"Parameter":"Cross-impact column sums", "Value":"Sum of each column", "Status":"Calculated if valid matrix" if matrix is not None else "Not run"},
    {"Parameter":"Factor grouping", "Value":"Median-based descriptive grouping", "Status":"Only if matrix valid; verify against course method" if matrix is not None else "Not run"},
    {"Parameter":"Kane’s Simulation", "Value":"Pending course-specific formula and inputs", "Status":"Not run"},
])
notes = [
    f"Dataset: {selected_name}",
    f"Rows: {len(original)}; columns: {len(original.columns)}.",
    f"Validation: {err_count} error(s), {warn_count} warning(s). Original data has been preserved.",
    "No missing values or cross-impact relationships were invented or imputed.",
    "Kane’s Simulation was not run because course-specific formulas were not supplied.",
    "Any cross-impact row/column sums and median-based groups are explicitly documented and should be checked against course materials.",
]
if matrix is not None and metrics is not None:
    notes.append("Cross-impact matrix was reviewed/edited in the interface; influence is row sum and dependence is column sum under the selected convention.")
    notes.append("The matrix export reflects the edited matrix currently displayed, while Original Data preserves the raw CSV.")
else:
    notes.append("Cross-impact analysis was not exported because a valid matrix was not available.")
try:
    xlsx_bytes = build_excel(original, selected_name, cleaned, validation, params, matrix, metrics, numeric_summary, notes)
    safe_stem = re.sub(r"[^A-Za-z0-9_-]+", "_", os.path.splitext(selected_name)[0]).strip("_") or "Dataset"
    report_name = f"Systems_Thinking_Report_{safe_stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    st.download_button("Download Complete Excel Report", data=xlsx_bytes, file_name=report_name, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary", use_container_width=True)
    st.caption("Each report is generated from the currently selected dataset. Upload/select another CSV to generate a separate report.")
except Exception as e:
    st.error(f"Excel export failed: {e}. Try a smaller file or a simpler column structure, then retry.")

st.divider()
st.caption("Systems Thinking Analysis Portal · Current version: general CSV validation, supported cross-impact analysis, numeric summaries, plots, and Excel export. Course-specific methods remain gated until their methodology is supplied.")
