from __future__ import annotations
from datetime import datetime
import io, os, re
import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st
from analysis_core import (validate_dataframe, coerce_numeric, detect_cross_impact,
    cross_impact_metrics, build_excel, run_ksim, denormalize_ksim, KSIM_METHOD)

st.set_page_config(page_title="Systems Thinking Analysis Portal", page_icon="🧭", layout="wide")
st.markdown("""<style>
.block-container {padding-top:1.5rem;padding-bottom:3rem;max-width:1500px}
.hero {padding:1.4rem 1.6rem;border-radius:16px;background:linear-gradient(120deg,#12263a,#245b78);color:white;margin-bottom:1rem}
.hero h1{color:white;margin:0}.hero p{color:#e4edf4;margin:.45rem 0 0}
</style><div class="hero"><h1>Systems Thinking Analysis Portal</h1><p>Upload, validate, analyse, visualize, and export your project data — including a documented KSIM simulation.</p></div>""", unsafe_allow_html=True)
with st.sidebar:
    st.header("Project workflow")
    st.markdown("1. Upload CSV\n2. Preview and validate\n3. Run cross-impact analysis\n4. Configure KSIM\n5. Download Excel report")
    st.divider()
    st.info("Each uploaded file is analysed independently. No missing data are silently imputed.")
    st.caption("Public app: do not upload confidential or personally identifying data.")
files = st.file_uploader("Upload one or more CSV files", type=["csv"], accept_multiple_files=True)
if not files:
    st.markdown("### Get started")
    st.write("Upload a CSV for preview, validation, cross-impact analysis and KSIM simulation.")
    st.info("KSIM can run from a square interaction matrix plus initial values and bounds. A CSV alone does not contain enough information unless those inputs are supplied.")
    st.stop()

names=[f.name for f in files]
selected=st.selectbox("Choose the dataset to analyse",names,key="selected_dataset")
uploaded=next(f for f in files if f.name==selected)
try:
    raw_bytes=uploaded.getvalue()
    try: original=pd.read_csv(io.BytesIO(raw_bytes),encoding="utf-8-sig")
    except UnicodeDecodeError: original=pd.read_csv(io.BytesIO(raw_bytes),encoding="latin-1")
except Exception as e:
    st.error(f"Could not read CSV: {e}"); st.stop()
if original.empty or not len(original.columns):
    st.error("This CSV has no usable data."); st.stop()
cleaned=coerce_numeric(original)
validation=validate_dataframe(original)
st.caption(f"Selected: {selected} · {len(original)} rows · {len(original.columns)} columns")
with st.expander("Preview uploaded data",expanded=False): st.dataframe(original.head(100),use_container_width=True)
st.header("1 · Validation")
st.dataframe(validation,use_container_width=True,hide_index=True)

st.header("2 · Cross-Impact Matrix")
colnames=list(original.columns)
src_default=next((c for c in colnames if str(c).lower().strip() in ["source","source_factor","from","cause"]),colnames[0])
tgt_default=next((c for c in colnames if str(c).lower().strip() in ["target","target_factor","to","effect"]),colnames[min(1,len(colnames)-1)])
val_default=next((c for c in colnames if str(c).lower().strip() in ["impact","impact_value","influence","weight","score","value"]),colnames[-1])
with st.expander("Map relationship columns (only if each row is a relationship)"):
    c1,c2,c3=st.columns(3)
    source_col=c1.selectbox("Source factor",colnames,index=colnames.index(src_default))
    target_col=c2.selectbox("Target factor",colnames,index=colnames.index(tgt_default))
    value_col=c3.selectbox("Impact / score",colnames,index=colnames.index(val_default))
matrix,msg=detect_cross_impact(original)
if matrix is None and len({source_col,target_col,value_col})==3:
    mapped,mmsg=detect_cross_impact(original,source_col,target_col,value_col)
    if mapped is not None: matrix,msg=mapped,mmsg
st.caption(msg)
metrics=None
if matrix is not None:
    st.write("Review matrix orientation: rows are treated as source factors for the portal's descriptive cross-impact metrics. KSIM uses rows as targets and columns as sources.")
    matrix=st.data_editor(matrix,use_container_width=True,key=f"matrix_{selected}")
    try:
        matrix=matrix.apply(pd.to_numeric,errors="raise")
        if matrix.isna().any().any(): st.error("Matrix contains missing cells."); matrix=None
        else:
            metrics,defs=cross_impact_metrics(matrix)
            a,b=st.columns(2)
            a.plotly_chart(px.imshow(matrix,text_auto=True,aspect="auto",title="Cross-impact heatmap"),use_container_width=True)
            b.plotly_chart(px.scatter(metrics,x="Dependence (column sum)",y="Influence (row sum)",text="Factor",title="Influence vs dependence"),use_container_width=True)
            st.dataframe(metrics,use_container_width=True,hide_index=True)
    except Exception as e:
        st.error(f"Matrix analysis error: {e}"); matrix=None

st.header("3 · Kane’s Simulation (KSIM)")
st.markdown("Provide a square interaction matrix and an initial value, minimum and maximum for every variable. KSIM converts the initial values to a normalized 0–1 scale before simulation.")
st.warning("Method transparency: this upgrade uses the documented KSIM-style ratio-exponent variant described below. It is a functional implementation, but should not be represented as identical to every published KSIM variant or to an unverified course-specific formula.")
with st.expander("Formula and assumptions",expanded=False):
    st.markdown("**Normalization:** `xᵢ(0) = (Xᵢ(0) − minimumᵢ) / (maximumᵢ − minimumᵢ)`.")
    st.markdown("**Interaction convention:** matrix row i is the target variable; column j is the source variable. Positive coefficients enhance the target; negative coefficients inhibit it.")
    st.markdown("**Update rule used:** `xᵢ(t+1) = xᵢ(t) ** (dt × Pᵢ(t))`, where `Pᵢ(t) = (weighted negative exposure + ε) / (weighted positive exposure + ε)`. The exposure weights are the current normalized source states. Thus positive influence dominance gives P below 1 and tends to increase a state; negative dominance gives P above 1 and tends to decrease it.")
    st.code(KSIM_METHOD)
    st.caption("This is an explicitly documented simplified variant based on published KSIM principles. Validate the exact update equation against your course requirements before academic submission.")
if matrix is None:
    st.info("Upload a valid square matrix to use it in KSIM, or enter the interaction matrix manually below.")
    var_names=st.text_input("Variable names, comma-separated","Demand,Price,Marketing,Customer_Satisfaction")
    names_ks=[x.strip() for x in var_names.split(",") if x.strip()]
    if len(names_ks)<2 or len(names_ks)>20:
        st.error("Enter between 2 and 20 unique variable names."); st.stop()
    default_A=pd.DataFrame(np.zeros((len(names_ks),len(names_ks))),index=names_ks,columns=names_ks)
    A=st.data_editor(default_A,use_container_width=True,key="manual_ksim_matrix")
else:
