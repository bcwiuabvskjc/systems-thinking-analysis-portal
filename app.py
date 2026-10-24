from __future__ import annotations
import json, os, io
from itertools import combinations
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from analysis_core import (
    KSIM_FORMULA, validate_matrix, parse_matrix_upload, make_template_xlsx,
    matrix_to_payload, matrix_from_payload, simulate_ksim, validate_reference_first_iteration, validate_reference_intervention,
)

st.set_page_config(page_title="Systems Thinking Analysis Portal", page_icon="🧭", layout="wide")
st.markdown("""
<style>
.block-container{padding-top:1.15rem;padding-bottom:3rem;max-width:1500px}
.hero{padding:1.25rem 1.5rem;border-radius:15px;background:linear-gradient(120deg,#13283d,#235c78);color:#fff;margin-bottom:1rem}
.hero h1{color:#fff;margin:0;font-size:2rem}.hero p{color:#e6f0f5;margin:.45rem 0 0}
div[data-testid="stMetric"]{background:rgba(120,140,160,.08);padding:12px;border-radius:10px;border:1px solid rgba(120,140,160,.18)}
.small-note{font-size:.9rem;color:var(--text-color)}
</style>
<div class="hero"><h1>Systems Thinking Analysis Portal</h1><p>Build the baseline, test interventions, and compare KSIM outcomes with transparent calculations.</p></div>
""", unsafe_allow_html=True)

# ---------- Supabase client and individual authentication ----------
def get_supabase():
    try:
        from supabase import create_client
        url = st.secrets.get("SUPABASE_URL", os.getenv("SUPABASE_URL", ""))
        key = st.secrets.get("SUPABASE_ANON_KEY", os.getenv("SUPABASE_ANON_KEY", ""))
        if not url or not key:
            return None, "Supabase credentials are not configured. Follow README.txt to create a project and add Streamlit Secrets."
        return create_client(url, key), None
    except Exception as exc:
        return None, f"Supabase setup error: {exc}"

sb, sb_error = get_supabase()
for key, default in [("auth_session", None), ("user", None), ("project_payload", None), ("project_id", None), ("project_name", "Untitled project"), ("loaded_initials", {})]:
    if key not in st.session_state:
        st.session_state[key] = default

if sb is None:
    st.error("Individual login and cloud saving need Supabase setup.")
    st.info(sb_error)
    st.stop()

# A new Streamlit rerun creates a new client. Restore the user's JWT on every rerun.
if st.session_state.auth_session:
    try:
        saved_session = st.session_state.auth_session
        restored = sb.auth.set_session(saved_session.access_token, saved_session.refresh_token)
        current_session = sb.auth.get_session()
        if current_session is not None:
            st.session_state.auth_session = current_session
        st.session_state.user = sb.auth.get_user().user
    except Exception:
        st.session_state.auth_session = None
        st.session_state.user = None

if not st.session_state.user:
    left, right = st.columns([1.25, 1])
    with left:
        st.subheader("Your personal systems-thinking workspace")
        st.write("Create an individual account to save your projects privately and reopen them later. No group workspaces or shared project access are used.")
        st.markdown("**Your workflow**")
        st.markdown("1. Define variables and upload or edit the cross-impact matrix.\n2. Run the AS-IS baseline with the professor-aligned KSIM formula.\n3. Define one or more interventions.\n4. Compare individual interventions and their combinations.\n5. Save the project to your account and export the results.")
    with right:
        tab_login, tab_signup = st.tabs(["Log in", "Create account"])
        with tab_login:
            with st.form("login_form"):
                email = st.text_input("Email address", key="login_email")
                password = st.text_input("Password", type="password", key="login_password")
                do_login = st.form_submit_button("Log in", type="primary", use_container_width=True)
            if do_login:
                try:
                    response = sb.auth.sign_in_with_password({"email": email.strip(), "password": password})
                    st.session_state.auth_session = response.session
                    st.session_state.user = response.user
                    st.rerun()
                except Exception as exc:
                    st.error(f"Login failed: {exc}")
        with tab_signup:
            with st.form("signup_form"):
                full_name = st.text_input("Full name")
                signup_email = st.text_input("Email address")
                signup_password = st.text_input("Password (at least 8 characters)", type="password")
                signup_confirm = st.text_input("Confirm password", type="password")
                do_signup = st.form_submit_button("Create account", type="primary", use_container_width=True)
            if do_signup:
                if not full_name.strip() or not signup_email.strip():
                    st.error("Enter your name and email address.")
                elif len(signup_password) < 8:
                    st.error("Use a password with at least 8 characters.")
                elif signup_password != signup_confirm:
                    st.error("Passwords do not match.")
                else:
                    try:
                        response = sb.auth.sign_up({"email": signup_email.strip(), "password": signup_password, "options": {"data": {"full_name": full_name.strip()}}})
                        if getattr(response, "session", None):
                            st.session_state.auth_session = response.session
                            st.session_state.user = response.user
                            st.success("Account created.")
                            st.rerun()
                        else:
                            st.success("Account created. If email confirmation is enabled, confirm your address and then log in.")
                    except Exception as exc:
                        st.error(f"Account creation failed: {exc}")
    st.stop()

user = st.session_state.user
uid = str(user.id)
with st.sidebar:
    st.markdown("### Account")
    st.write(getattr(user, "email", "Signed in"))
    if st.button("Log out", use_container_width=True):
        try:
            sb.auth.sign_out()
        except Exception:
            pass
        for k in ["auth_session", "user", "project_id", "project_payload"]:
            st.session_state[k] = None
        st.rerun()
    st.divider()
    st.markdown("### My projects")
    if st.button("＋ New project", use_container_width=True):
        st.session_state.project_id = None
        st.session_state.project_payload = None
        st.session_state.project_name = "Untitled project"
        blank_names = ["Variable 1", "Variable 2", "Variable 3", "Variable 4"]
        st.session_state.asis_matrix_payload = matrix_to_payload(pd.DataFrame(np.zeros((4,4)), index=blank_names, columns=blank_names))
        st.session_state.initial_values_payload = None
        st.session_state.interventions_payload = []
        st.session_state.rules_payload = []
        st.session_state.pop("asis_matrix_editor", None)
        st.session_state.pop("initial_values_editor", None)
        st.session_state.pop("interventions_editor", None)
        st.session_state.pop("relationship_rules_editor", None)
        st.session_state.pop("simulation_results", None)
        st.session_state.pop("project_name_input", None)
        st.session_state.pop("problem_statement", None)
        st.session_state.pop("variable_names_text", None)
        st.session_state.pop("variable_descriptions_editor", None)
        st.session_state.pop("asis_result", None)
        st.session_state.pop("asis_detail", None)
        st.session_state.pop("scenario_results", None)
        st.session_state.pop("simulation_settings", None)
        st.rerun()
    try:
        saved_projects = sb.table("projects").select("id,name,updated_at,payload").eq("user_id", uid).order("updated_at", desc=True).execute().data or []
    except Exception as exc:
        saved_projects = []
        st.warning(f"Saved projects unavailable: {exc}")
    project_lookup = {f"{p['name']} · {str(p.get('updated_at',''))[:10]}": p for p in saved_projects}
    chosen_saved = st.selectbox("Open saved project", ["— Select —"] + list(project_lookup), key="saved_project_picker")
    if chosen_saved != "— Select —" and st.button("Load project", use_container_width=True):
        selected_project = project_lookup[chosen_saved]
        st.session_state.project_id = selected_project["id"]
        st.session_state.project_payload = selected_project.get("payload") or {}
        st.session_state.project_name = selected_project.get("name", "Untitled project")
        loaded_payload = st.session_state.project_payload
        loaded_matrix = matrix_from_payload(loaded_payload.get("asis_matrix"))
        if loaded_matrix is not None:
            st.session_state.asis_matrix_payload = matrix_to_payload(loaded_matrix)
        st.session_state.initial_values_payload = loaded_payload.get("initial_values")
        st.session_state.interventions_payload = loaded_payload.get("interventions", [])
        st.session_state.rules_payload = loaded_payload.get("relationship_rules", [])
        # clear keyed editors so they initialise from the loaded project
        for k in ["asis_matrix_editor", "initial_values_editor", "interventions_editor", "relationship_rules_editor", "variable_descriptions_editor", "variable_names_text", "problem_statement", "project_name_input"]:
            st.session_state.pop(k, None)
        st.session_state.pop("simulation_results", None)
        st.rerun()
    st.caption("Each account can access only its own saved projects.")

payload = st.session_state.project_payload or {}

# ---------- Restore or initialize project data ----------
def demo_matrix():
    names = ["Parthenium abundance", "Asthma incidence", "Happiness level", "Government seriousness", "Hospital admissions", "Expert committee involvement"]
    vals = np.array([
        [0.3, 0, 0, -0.1, 0, 0],
        [0.7, -0.2, -0.2, -0.3, 0, -0.1],
        [0, -0.8, 0.4, 0.1, -0.7, 0],
        [0.6, 0.7, -0.5, -0.2, 0.5, 0.6],
        [0.7, 0.3, -0.1, -0.1, -0.2, -0.1],
        [0.5, 0.5, -0.5, 0.7, 0.6, 0.5],
    ], dtype=float)
    return pd.DataFrame(vals, index=names, columns=names)

if "asis_matrix_payload" not in st.session_state:
    restored_matrix = matrix_from_payload(payload.get("asis_matrix"))
    st.session_state.asis_matrix_payload = matrix_to_payload(restored_matrix if restored_matrix is not None else pd.DataFrame(np.zeros((4,4)), index=["Variable 1","Variable 2","Variable 3","Variable 4"], columns=["Variable 1","Variable 2","Variable 3","Variable 4"]))
if "initial_values_payload" not in st.session_state:
    st.session_state.initial_values_payload = payload.get("initial_values", None)
if "interventions_payload" not in st.session_state:
    st.session_state.interventions_payload = payload.get("interventions", [])
if "rules_payload" not in st.session_state:
    st.session_state.rules_payload = payload.get("relationship_rules", [])

matrix = matrix_from_payload(st.session_state.asis_matrix_payload)
if matrix is None:
    matrix = pd.DataFrame(np.zeros((4,4)), index=["Variable 1","Variable 2","Variable 3","Variable 4"], columns=["Variable 1","Variable 2","Variable 3","Variable 4"])

with st.sidebar:
    st.divider()
    st.markdown("### Project details")
    project_name = st.text_input("Project name", value=st.session_state.project_name or "Untitled project", key="project_name_input")
    st.session_state.project_name = project_name

# ---------- Workflow navigation ----------
tabs = st.tabs(["1 · Define & upload", "2 · AS-IS analysis", "3 · TO-BE interventions", "4 · Compare & export"])

with tabs[0]:
    st.header("Define your system")
    st.write("Describe the problem and name the variables before building the matrix. You can upload a matrix or edit it directly.")
    problem = st.text_area("Problem statement", value=payload.get("problem", ""), placeholder="What system or problem are you analysing?", key="problem_statement")
    variable_names_text = st.text_area("Variable names — one per line", value="\n".join(matrix.index.astype(str)), height=130, key="variable_names_text", help="Use exactly the same variable names in matrix rows and columns. Renaming or changing the number of variables resets the matrix unless you upload a matching file.")
    names = [v.strip() for v in variable_names_text.splitlines() if v.strip()]
    names_changed = names != list(matrix.index) or names != list(matrix.columns)
    col_a, col_b, col_c = st.columns([1.2, 1.2, 1])
    with col_a:
        uploaded_matrix = st.file_uploader("Upload cross-impact matrix (.xlsx or .csv)", type=["xlsx", "csv"], key="matrix_upload")
        if st.button("Import uploaded matrix", disabled=uploaded_matrix is None, use_container_width=True):
            try:
                uploaded_matrix.seek(0)
                imported, imported_initials, message = parse_matrix_upload(uploaded_matrix)
                st.session_state.asis_matrix_payload = matrix_to_payload(imported)
                st.session_state.initial_values_payload = imported_initials or None
                st.session_state.pop("asis_matrix_editor", None)
                st.session_state.pop("initial_values_editor", None)
                st.session_state.pop("relationship_rules_editor", None)
                st.session_state.pop("variable_names_text", None)
                st.success(f"{message} Variables: {len(imported)}.")
                st.rerun()
            except Exception as exc:
                st.error(f"Could not import matrix: {exc}")
    with col_b:
        template_names = names if len(names) >= 2 else None
        st.download_button("Download Excel matrix template", data=make_template_xlsx(template_names), file_name="systems_thinking_matrix_template.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
        csv_names = template_names or ["Variable 1", "Variable 2", "Variable 3", "Variable 4"]
        csv_template = pd.DataFrame(np.zeros((len(csv_names),len(csv_names))), index=csv_names, columns=csv_names).to_csv(index=True, index_label="Variable").encode("utf-8")
        st.download_button("Download CSV matrix template", data=csv_template, file_name="systems_thinking_matrix_template.csv", mime="text/csv", use_container_width=True)
    with col_c:
        if st.button("Load professor's Parthenium example", use_container_width=True):
            dm = demo_matrix()
            st.session_state.asis_matrix_payload = matrix_to_payload(dm)
            st.session_state.initial_values_payload = {n: {"Initial value":v,"Minimum":0.0,"Maximum":1.0} for n,v in zip(dm.index, [0.5,0.35,0.35,0.3,0.3,0.1])}
            st.session_state.interventions_payload = [{"Enabled":True,"Intervention":"Biological-control beetle","Type":"New variable","Variable name":"Beetle abundance","Description":"Introduced to reduce Parthenium abundance","Start period":4,"Initial value":0.3,"Minimum":0.0,"Maximum":1.0}]
            st.session_state.rules_payload = [
                {"Intervention":"Biological-control beetle","Target variable":"Parthenium abundance","Source variable":"Beetle abundance","Impact":-0.9,"Start period":0},
                {"Intervention":"Biological-control beetle","Target variable":"Happiness level","Source variable":"Parthenium abundance","Impact":-0.7,"Start period":0},
                {"Intervention":"Biological-control beetle","Target variable":"Happiness level","Source variable":"Beetle abundance","Impact":0.1,"Start period":0},
                {"Intervention":"Biological-control beetle","Target variable":"Government seriousness","Source variable":"Beetle abundance","Impact":-0.3,"Start period":0},
                {"Intervention":"Biological-control beetle","Target variable":"Expert committee involvement","Source variable":"Beetle abundance","Impact":-0.3,"Start period":0},
                {"Intervention":"Biological-control beetle","Target variable":"Beetle abundance","Source variable":"Beetle abundance","Impact":0.5,"Start period":0},
            ]
            for k in ["asis_matrix_editor","initial_values_editor","interventions_editor","relationship_rules_editor","variable_names_text"]: st.session_state.pop(k, None)
            st.rerun()
    if names_changed:
        st.warning("Your variable list differs from the current matrix. Apply the new list to rebuild a zero-filled matrix, or import a matching matrix.")
        if st.button("Apply variable list and rebuild matrix", type="secondary"):
            if len(names) < 2 or len(names) > 20:
                st.error("Enter between 2 and 20 variable names.")
            elif len(set(names)) != len(names):
                st.error("Variable names must be unique.")
            else:
                old = matrix
                new = pd.DataFrame(np.zeros((len(names),len(names))), index=names, columns=names)
                common = [n for n in names if n in old.index and n in old.columns]
                if common: new.loc[common, common] = old.loc[common, common].to_numpy()
                st.session_state.asis_matrix_payload = matrix_to_payload(new)
                st.session_state.pop("asis_matrix_editor", None)
                st.session_state.pop("initial_values_editor", None)
                st.rerun()
    matrix = matrix_from_payload(st.session_state.asis_matrix_payload)
    st.subheader("AS-IS cross-impact matrix")
    st.caption("Rows are the affected variables; columns are the influencing variables. Positive values reinforce; negative values inhibit. Use -1 to +1.")
    if matrix is not None:
        edited_matrix = st.data_editor(matrix, use_container_width=True, key="asis_matrix_editor", num_rows="fixed", column_config={c: st.column_config.NumberColumn(c, min_value=-1.0, max_value=1.0, step=0.1, format="%.2f") for c in matrix.columns})
        edited_matrix.index = matrix.index
        st.session_state.asis_matrix_payload = matrix_to_payload(edited_matrix)
        matrix_signature = json.dumps(matrix_to_payload(edited_matrix), sort_keys=True)
        prior_matrix_signature = st.session_state.get("last_matrix_signature")
        if prior_matrix_signature is not None and prior_matrix_signature != matrix_signature:
            for result_key in ["asis_result", "asis_detail", "scenario_results", "simulation_settings", "asis_signature"]:
                st.session_state.pop(result_key, None)
        st.session_state.last_matrix_signature = matrix_signature
        validation = validate_matrix(edited_matrix)
        st.dataframe(validation, use_container_width=True, hide_index=True)
        st.download_button("Download current AS-IS matrix (CSV)", edited_matrix.to_csv(index=True, index_label="Variable").encode("utf-8"), "asis_matrix.csv", "text/csv")
    st.subheader("Variable descriptions")
    desc_default = payload.get("variable_descriptions", [{"Variable":n,"Description":""} for n in matrix.index])
    desc_df = pd.DataFrame(desc_default)
    if "Variable" not in desc_df: desc_df["Variable"] = list(matrix.index)
    if "Description" not in desc_df: desc_df["Description"] = ""
    desc_df = desc_df.set_index("Variable").reindex(matrix.index).reset_index()
    descriptions = st.data_editor(desc_df, use_container_width=True, hide_index=True, num_rows="fixed", key="variable_descriptions_editor", disabled=["Variable"])

with tabs[1]:
    st.header("AS-IS · Baseline analysis")
    matrix = matrix_from_payload(st.session_state.asis_matrix_payload)
    if matrix is None:
        st.error("Define or upload a valid matrix first.")
    else:
        st.subheader("Initial values and simulation settings")
        init_saved = st.session_state.initial_values_payload or {}
        init_rows = []
        for n in matrix.index:
            item = init_saved.get(n, {}) if isinstance(init_saved, dict) else {}
            defaults = {"Variable":n, "Initial value":item.get("Initial value",0.5), "Minimum":item.get("Minimum",0.0), "Maximum":item.get("Maximum",1.0)}
            init_rows.append(defaults)
        init_df = pd.DataFrame(init_rows)
        initial_editor = st.data_editor(init_df, use_container_width=True, hide_index=True, num_rows="fixed", disabled=["Variable"], key="initial_values_editor", column_config={"Initial value":st.column_config.NumberColumn("Initial value", step=0.05),"Minimum":st.column_config.NumberColumn("Minimum",step=0.05),"Maximum":st.column_config.NumberColumn("Maximum",step=0.05)})
        st.session_state.initial_values_payload = {r["Variable"]:{"Initial value":float(r["Initial value"]),"Minimum":float(r["Minimum"]),"Maximum":float(r["Maximum"])} for r in initial_editor.to_dict("records")}
        initial_signature = json.dumps(st.session_state.initial_values_payload, sort_keys=True)
        prior_initial_signature = st.session_state.get("last_initial_signature")
        if prior_initial_signature is not None and prior_initial_signature != initial_signature:
            for result_key in ["asis_result", "asis_detail", "scenario_results", "simulation_settings", "asis_signature"]:
                st.session_state.pop(result_key, None)
        st.session_state.last_initial_signature = initial_signature
        c1,c2 = st.columns(2)
        with c1: steps = int(st.number_input("Simulation periods after T0", min_value=1, max_value=50, value=int(payload.get("steps",10)), step=1, key="simulation_steps"))
        with c2: dt = float(st.number_input("Time-step multiplier (Δt)", min_value=0.1, max_value=2.0, value=float(payload.get("dt",1.0)), step=0.1, key="simulation_dt"))
        config_signature = json.dumps({"steps":steps,"dt":dt}, sort_keys=True)
        prior_config_signature = st.session_state.get("last_config_signature")
        if prior_config_signature is not None and prior_config_signature != config_signature:
            for result_key in ["asis_result", "asis_detail", "scenario_results", "simulation_settings", "asis_signature"]:
                st.session_state.pop(result_key, None)
        st.session_state.last_config_signature = config_signature
        st.markdown("**KSIM formula used**")
        st.latex(r"p_i(t)=\frac{1+\frac{\Delta t}{2}\sum_j(|a_{ij}|-a_{ij})x_j(t)}{1+\frac{\Delta t}{2}\sum_j(|a_{ij}|+a_{ij})x_j(t)}")
        st.latex(r"x_i(t+\Delta t)=x_i(t)^{p_i(t)}")
        with st.expander("What each calculation means", expanded=False):
            st.markdown("- **Numerator:** 1 plus the weighted inhibiting influence on the target variable.\n- **Denominator:** 1 plus the weighted reinforcing influence on the target variable.\n- **Exponent:** numerator divided by denominator.\n- **Next state:** current normalized state raised to the calculated exponent.\n- **Normalization:** original values are mapped to 0–1 using each variable's minimum and maximum, then converted back for display.")
        if st.button("Run AS-IS baseline", type="primary", use_container_width=True):
            try:
                mat_validation = validate_matrix(matrix)
                if (mat_validation["Status"] == "Error").any(): raise ValueError("Fix matrix validation errors in Define & upload first.")
                init_map = {r["Variable"]:float(r["Initial value"]) for r in initial_editor.to_dict("records")}
                min_map = {r["Variable"]:float(r["Minimum"]) for r in initial_editor.to_dict("records")}
                max_map = {r["Variable"]:float(r["Maximum"]) for r in initial_editor.to_dict("records")}
                result, detail = simulate_ksim(list(matrix.index), matrix, init_map, steps, dt, minimums=min_map, maximums=max_map)
                st.session_state.asis_result = result
                st.session_state.asis_detail = detail
                st.session_state.simulation_settings = {"steps":steps,"dt":dt,"initial_values":init_map,"minimums":min_map,"maximums":max_map}
                st.session_state.asis_signature = json.dumps({"matrix":matrix_to_payload(matrix),"initial":st.session_state.initial_values_payload,"steps":steps,"dt":dt}, sort_keys=True)
                st.success("AS-IS baseline calculated.")
            except Exception as exc:
                st.error(f"Could not run AS-IS: {exc}")
        if "asis_result" in st.session_state:
            result = st.session_state.asis_result
            detail = st.session_state.asis_detail
            metrics = st.columns(3)
            metrics[0].metric("Variables", len(matrix))
            metrics[1].metric("Periods", len(result)-1)
            metrics[2].metric("KSIM method", "Professor workbook formula")
            chart_df = result.melt(id_vars="Time", var_name="Variable", value_name="State")
            fig = px.line(chart_df, x="Time", y="State", color="Variable", markers=True, title="AS-IS baseline trajectories")
            fig.update_layout(hovermode="x unified", legend_title="Variable", xaxis_title="Simulation period", yaxis_title="State (original scale)", margin=dict(l=20,r=20,t=60,b=20))
            fig.update_traces(line=dict(width=2.6), marker=dict(size=5))
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(result, use_container_width=True, hide_index=True)
            st.subheader("KSIM calculation details")
            selected_t = st.selectbox("Show calculation for transition", sorted(detail["From time"].unique(), key=lambda x:int(x[1:])), key="asis_detail_time")
            st.dataframe(detail[detail["From time"] == selected_t].drop(columns=["From time","To time","Matrix active at step"]), use_container_width=True, hide_index=True)
            st.download_button("Download AS-IS results (CSV)", result.to_csv(index=False).encode(), "asis_results.csv", "text/csv")

with tabs[2]:
    st.header("TO-BE · Define interventions")
    st.write("Add as many interventions as your model needs. Each can introduce a new variable or modify existing relationships. Impacts must be entered explicitly; the portal does not invent causal values.")
    matrix = matrix_from_payload(st.session_state.asis_matrix_payload)
    if matrix is None: matrix = pd.DataFrame()
    default_interventions = st.session_state.interventions_payload or []
    interventions_df = pd.DataFrame(default_interventions, columns=["Enabled","Intervention","Type","Variable name","Description","Start period","Initial value","Minimum","Maximum"])
    if interventions_df.empty:
        interventions_df = pd.DataFrame(columns=["Enabled","Intervention","Type","Variable name","Description","Start period","Initial value","Minimum","Maximum"])
    interventions_df = st.data_editor(interventions_df, use_container_width=True, hide_index=True, num_rows="dynamic", key="interventions_editor", column_config={
        "Enabled":st.column_config.CheckboxColumn("Include in analysis",default=True),
        "Intervention":st.column_config.TextColumn("Intervention name",required=True),
        "Type":st.column_config.SelectboxColumn("Intervention type",options=["New variable","Modify existing relationships"],required=True),
        "Variable name":st.column_config.TextColumn("New variable name (if applicable)"),
        "Description":st.column_config.TextColumn("Description / rationale"),
        "Start period":st.column_config.NumberColumn("Start at T",min_value=0,max_value=50,step=1,default=0),
        "Initial value":st.column_config.NumberColumn("New variable initial value",min_value=0.0,max_value=1.0,step=0.05,default=0.3),
        "Minimum":st.column_config.NumberColumn("Minimum",min_value=0.0,max_value=1.0,step=0.05,default=0.0),
        "Maximum":st.column_config.NumberColumn("Maximum",min_value=0.01,max_value=1.0,step=0.05,default=1.0),
    })
    # Normalize empty/new rows and retain non-empty intervention definitions.
    interventions_df = interventions_df.fillna({"Enabled":False,"Intervention":"","Type":"Modify existing relationships","Variable name":"","Description":"","Start period":0,"Initial value":0.3,"Minimum":0.0,"Maximum":1.0})
    interventions_df["Intervention"] = interventions_df["Intervention"].astype(str).str.strip()
    interventions_df = interventions_df[interventions_df["Intervention"].ne("")].copy()
    intervention_signature = json.dumps(interventions_df.fillna("").to_dict("records"), sort_keys=True, default=str)
    prior_intervention_signature = st.session_state.get("last_intervention_signature")
    if prior_intervention_signature is not None and prior_intervention_signature != intervention_signature:
        st.session_state.pop("scenario_results", None)
    st.session_state.last_intervention_signature = intervention_signature
    st.session_state.interventions_payload = interventions_df.to_dict("records")
    base_names = list(matrix.index) if not matrix.empty else []
    intervention_vars = []
    for _, row in interventions_df.iterrows():
        if row["Type"] == "New variable":
            nm = str(row.get("Variable name", "")).strip()
            if nm:
                intervention_vars.append(nm)
    all_possible_names = base_names + [n for n in dict.fromkeys(intervention_vars) if n not in base_names]
    if len(all_possible_names) > 20:
        st.error("AS-IS plus new intervention variables exceeds the 20-variable limit. Reduce the number of variables.")
    st.subheader("Define intervention relationships")
    st.caption("Each row changes one cell: the target is the affected variable, the source is the influencing variable, and impact is the signed coefficient. You can define multiple rows for the same intervention.")
    rules_df = pd.DataFrame(st.session_state.rules_payload or [], columns=["Intervention","Target variable","Source variable","Impact","Start period"])
    if rules_df.empty: rules_df = pd.DataFrame(columns=["Intervention","Target variable","Source variable","Impact","Start period"])
    intervention_options = interventions_df["Intervention"].tolist() if not interventions_df.empty else []
    rules_df = st.data_editor(rules_df, use_container_width=True, hide_index=True, num_rows="dynamic", key="relationship_rules_editor", column_config={
        "Intervention":st.column_config.SelectboxColumn("Which intervention?",options=intervention_options,required=True),
        "Target variable":st.column_config.SelectboxColumn("Affected variable (row)",options=all_possible_names,required=True),
        "Source variable":st.column_config.SelectboxColumn("Influencing variable (column)",options=all_possible_names,required=True),
        "Impact":st.column_config.NumberColumn("New impact (-1 to +1)",min_value=-1.0,max_value=1.0,step=0.1,required=True),
        "Start period":st.column_config.NumberColumn("Relationship active from T",min_value=0,max_value=50,step=1,default=0,required=True),
    })
    rules_df = rules_df.dropna(subset=["Intervention","Target variable","Source variable","Impact"], how="any")
    if "Start period" not in rules_df: rules_df["Start period"] = 0
    rules_df["Start period"] = pd.to_numeric(rules_df["Start period"], errors="coerce").fillna(0).astype(int)
    rules_signature = json.dumps(rules_df.fillna("").to_dict("records"), sort_keys=True, default=str)
    prior_rules_signature = st.session_state.get("last_rules_signature")
    if prior_rules_signature is not None and prior_rules_signature != rules_signature:
        st.session_state.pop("scenario_results", None)
    st.session_state.last_rules_signature = rules_signature
    st.session_state.rules_payload = rules_df.to_dict("records")
    st.subheader("Review what will change")
    enabled = interventions_df[interventions_df["Enabled"].astype(bool)] if not interventions_df.empty else interventions_df
    if enabled.empty:
        st.info("Add an intervention and tick 'Include in analysis'.")
    else:
        st.write(f"**{len(enabled)} enabled intervention(s).** The portal will run each one individually and can run combinations too.")
        st.dataframe(enabled[["Intervention","Type","Variable name","Description","Start period"]], use_container_width=True, hide_index=True)
        if len(enabled) >= 2:
            st.info("For 2–6 enabled interventions, the run will include every combination of two or more interventions. This makes it possible to inspect combined effects as well as individual effects. If more than 6 are enabled, the portal runs individual scenarios and the full selected combination to keep computation manageable.")
    with st.expander("How interventions are applied", expanded=False):
        st.markdown("- A **new variable** is added to the scenario matrix with zero relationships until you define them. Its state is set to the specified initial value at its start period.\n- A **relationship modification** changes the specified matrix cell from its own “Relationship active from T” period onward. This can be earlier than a new variable's introduction time, as in the professor's workbook.\n- The baseline matrix remains unchanged.\n- If multiple selected interventions assign different values to the same matrix cell, that scenario is marked as a conflict rather than silently choosing one value.\n- Start periods refer to state times: an intervention starting at T4 is active for the transition from T4 to T5.")

with tabs[3]:
    st.header("Compare scenarios and export")
    matrix = matrix_from_payload(st.session_state.asis_matrix_payload)
    if matrix is None:
        st.info("Define an AS-IS matrix first.")
    else:
        if "asis_result" not in st.session_state:
            st.info("Run the AS-IS baseline in the AS-IS analysis tab first. Then run the TO-BE scenarios below.")
        settings = st.session_state.get("simulation_settings")
        if settings is None:
            # Use current editor values if baseline not run; this section can still report the next required action.
            st.stop()
        interventions_df = pd.DataFrame(st.session_state.interventions_payload or [])
        rules_df = pd.DataFrame(st.session_state.rules_payload or [])
        if not interventions_df.empty:
            enabled = interventions_df[interventions_df["Enabled"].astype(bool)].copy()
        else:
            enabled = pd.DataFrame()
        if st.button("Run individual interventions and combinations", type="primary", use_container_width=True):
            try:
                scenarios = {"AS-IS": {"result":st.session_state.asis_result.copy(), "detail":st.session_state.asis_detail.copy(), "matrix":matrix.copy(), "interventions":[]}}
                enabled_names = enabled["Intervention"].astype(str).tolist() if not enabled.empty else []
                if len(enabled_names) != len(set(enabled_names)):
                    raise ValueError("Intervention names must be unique.")
                definitions = {str(r["Intervention"]):r.to_dict() for _,r in enabled.iterrows()}
                if len(definitions) > 0:
                    labels = list(definitions)
                    sets = [(name,) for name in labels]
                    if 2 <= len(labels) <= 6:
                        for r in range(2, len(labels)+1):
                            sets.extend(list(combinations(labels, r)))
                    elif len(labels) > 6:
                        sets.append(tuple(labels))
                    # Remove duplicate intervention labels from scenario generation; names must be unique.
                    if len(labels) != len(set(labels)):
                        raise ValueError("Intervention names must be unique.")
                    for combo in sets:
                        scenario_label = " + ".join(combo)
                        chosen_defs = [definitions[n] for n in combo]
                        scenario_names = list(matrix.index)
                        for row in chosen_defs:
                            if row.get("Type") == "New variable":
                                vn = str(row.get("Variable name", "")).strip()
                                if not vn: raise ValueError(f"Intervention '{row['Intervention']}' is set to New variable but has no variable name.")
                                if vn in matrix.index and vn not in scenario_names: scenario_names.append(vn)
                                elif vn not in scenario_names: scenario_names.append(vn)
                        if len(scenario_names) > 20:
                            raise ValueError(f"Scenario '{scenario_label}' has more than 20 variables.")
                        scenario_matrix = pd.DataFrame(np.zeros((len(scenario_names),len(scenario_names))), index=scenario_names, columns=scenario_names)
                        scenario_matrix.loc[matrix.index,matrix.columns] = matrix.to_numpy()
                        included_rules = []
                        cell_owners = {}
                        for rule in (rules_df.to_dict("records") if not rules_df.empty else []):
                            if str(rule.get("Intervention")) not in combo: continue
                            target = str(rule["Target variable"]); source = str(rule["Source variable"]); impact = float(rule["Impact"])
                            if target not in scenario_names or source not in scenario_names:
                                raise ValueError(f"Rule for '{rule['Intervention']}' refers to a variable that is not in scenario '{scenario_label}'.")
                            key = (target, source)
                            prior = cell_owners.get(key)
                            if prior and not np.isclose(prior["impact"], impact):
                                raise ValueError(f"Conflict in scenario '{scenario_label}': {prior['intervention']} and {rule['Intervention']} set {target} ← {source} to different impacts. Resolve the conflict in the relationship table.")
                            cell_owners[key] = {"intervention":str(rule["Intervention"]),"impact":impact}
                            d = definitions[str(rule["Intervention"])]
                            included_rules.append({"target":target,"source":source,"impact":impact,"start_period":int(rule.get("Start period",0))})
                        initial_map = dict(settings["initial_values"])
                        min_map = dict(settings["minimums"]); max_map = dict(settings["maximums"])
                        activations = []
                        for row in chosen_defs:
                            if row.get("Type") == "New variable":
                                vn = str(row.get("Variable name", "")).strip()
                                if vn in matrix.index:
                                    raise ValueError(f"New variable '{vn}' duplicates an existing AS-IS variable.")
                                min_map[vn] = float(row.get("Minimum",0.0)); max_map[vn] = float(row.get("Maximum",1.0))
                                start_t = int(row.get("Start period",0))
                                initial_map[vn] = float(row.get("Minimum",0.0)) if start_t > 0 else float(row.get("Initial value",0.3))
                                activations.append({"variable":vn,"start_period":start_t,"initial_value":float(row.get("Initial value",0.3))})
                        # Initial values for variables introduced by other interventions are excluded from this scenario.
                        scenario_initial = {n:initial_map[n] for n in scenario_names if n in initial_map}
                        scenario_min = {n:min_map.get(n,0.0) for n in scenario_names}
                        scenario_max = {n:max_map.get(n,1.0) for n in scenario_names}
                        result, detail = simulate_ksim(scenario_names, scenario_matrix, scenario_initial, settings["steps"], settings["dt"], activations=activations, relationship_events=included_rules, minimums=scenario_min, maximums=scenario_max)
                        display_matrix = scenario_matrix.copy()
                        for event in included_rules:
                            display_matrix.loc[event["target"], event["source"]] = event["impact"]
                        scenarios[scenario_label] = {"result":result,"detail":detail,"matrix":display_matrix,"interventions":list(combo)}
                st.session_state.scenario_results = scenarios
                st.success(f"Calculated {len(scenarios)-1} intervention scenario(s), plus AS-IS.")
            except Exception as exc:
                st.error(f"Scenario calculation stopped: {exc}")
        scenarios = st.session_state.get("scenario_results")
        if scenarios:
            scenario_names = list(scenarios)
            default_display = ["AS-IS"]
            if len(scenario_names) > 1:
                # Default to AS-IS plus the full combined scenario when present, otherwise first individual.
                all_enabled = " + ".join(enabled["Intervention"].astype(str).tolist()) if not enabled.empty else None
                if all_enabled in scenario_names and all_enabled != "AS-IS": default_display.append(all_enabled)
                elif scenario_names[1] not in default_display: default_display.append(scenario_names[1])
            display_scenarios = st.multiselect("Scenarios to show on comparison graphs", scenario_names, default=default_display, key="comparison_scenario_picker")
            common_vars = list(matrix.index)
            selected_vars = st.multiselect("Variables to compare", common_vars, default=common_vars[:min(5,len(common_vars))], key="comparison_variable_picker")
            if display_scenarios and selected_vars:
                plot_rows=[]; difference_rows=[]
                baseline = scenarios["AS-IS"]["result"].set_index("Time")
                for scenario in display_scenarios:
                    frame = scenarios[scenario]["result"]
                    for _, row in frame.iterrows():
                        for var in selected_vars:
                            if var in frame.columns:
                                plot_rows.append({"Time":row["Time"],"Variable":var,"State":row[var],"Scenario":scenario})
                                if scenario != "AS-IS" and var in baseline.columns:
                                    base_value = float(baseline.loc[row["Time"],var])
                                    difference_rows.append({"Time":row["Time"],"Variable":var,"Difference from AS-IS":float(row[var])-base_value,"Scenario":scenario})
                plot_df = pd.DataFrame(plot_rows)
                fig = px.line(plot_df, x="Time", y="State", color="Scenario", facet_col="Variable", facet_col_wrap=2, markers=True, title="Scenario trajectories")
                fig.update_layout(hovermode="x unified", legend_title="Scenario", xaxis_title="Simulation period", yaxis_title="State (original scale)", margin=dict(l=20,r=20,t=70,b=20))
                fig.update_traces(line=dict(width=2.6), marker=dict(size=4))
                st.plotly_chart(fig, use_container_width=True)
                if not pd.DataFrame(difference_rows).empty:
                    diff_df = pd.DataFrame(difference_rows)
                    diff_fig = px.line(diff_df, x="Time", y="Difference from AS-IS", color="Scenario", facet_col="Variable", facet_col_wrap=2, markers=True, title="Difference from baseline (TO-BE minus AS-IS)")
                    diff_fig.add_hline(y=0, line_dash="dash", line_color="gray")
                    diff_fig.update_layout(hovermode="x unified", xaxis_title="Simulation period", yaxis_title="Absolute difference in original units", margin=dict(l=20,r=20,t=70,b=20))
                    st.plotly_chart(diff_fig, use_container_width=True)
            # Heatmap showing AS-IS matrix and the selected scenario matrix difference.
            heat_scenario = st.selectbox("Matrix to inspect", scenario_names, index=1 if len(scenario_names)>1 else 0, key="matrix_heatmap_scenario")
            heat_matrix = scenarios[heat_scenario]["matrix"]
            hm = px.imshow(heat_matrix, x=list(heat_matrix.columns), y=list(heat_matrix.index), color_continuous_scale="RdBu_r", zmin=-1, zmax=1, aspect="auto", text_auto=".2f", title=f"Cross-impact matrix · {heat_scenario}")
            hm.update_layout(xaxis_title="Influencing variable (column)", yaxis_title="Affected variable (row)", margin=dict(l=20,r=20,t=60,b=20))
            st.plotly_chart(hm, use_container_width=True)
            detail_scenario = st.selectbox("Inspect KSIM calculation steps for", scenario_names, key="detail_scenario_picker")
            detail_frame = scenarios[detail_scenario]["detail"]
            if not detail_frame.empty:
                detail_time = st.selectbox("Transition", sorted(detail_frame["From time"].unique(), key=lambda x:int(x[1:])), key="detail_time_picker")
                st.dataframe(detail_frame[detail_frame["From time"]==detail_time].drop(columns=["From time","To time","Matrix active at step"]), use_container_width=True, hide_index=True)
            st.subheader("Scenario summary")
            summary_rows=[]
            for sc, obj in scenarios.items():
                rr = obj["result"]
                last = rr.iloc[-1]
                row={"Scenario":sc,"Interventions":"; ".join(obj["interventions"]),"Variables":len(rr.columns)-1,"Final period":rr.iloc[-1]["Time"]}
                for var in selected_vars:
                    if var in last.index: row[f"Final · {var}"]=last[var]
                summary_rows.append(row)
            st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)
            st.subheader("Download results")
            out = io.BytesIO()
            with pd.ExcelWriter(out, engine="openpyxl") as writer:
                matrix.to_excel(writer, sheet_name="AS-IS Matrix")
                used_sheets = {"AS-IS Matrix"}
                def unique_sheet(base):
                    base = (base or "Scenario")[:31]
                    candidate = base
                    serial = 2
                    while candidate in used_sheets:
                        suffix = f"_{serial}"
                        candidate = base[:31-len(suffix)] + suffix
                        serial += 1
                    used_sheets.add(candidate)
                    return candidate
                for i,(sc,obj) in enumerate(scenarios.items()):
                    safe = "".join(ch if ch.isalnum() else "_" for ch in sc)[:22] or f"Scenario{i}"
                    obj["result"].to_excel(writer, sheet_name=unique_sheet(safe), index=False)
                    if not obj["detail"].empty:
                        obj["detail"].to_excel(writer, sheet_name=unique_sheet(safe[:20] + "_Calc"), index=False)
                    obj["matrix"].to_excel(writer, sheet_name=unique_sheet(safe[:21] + "_Matrix"))
                if not interventions_df.empty: interventions_df.to_excel(writer, sheet_name="Interventions", index=False)
                if not rules_df.empty: rules_df.to_excel(writer, sheet_name="Relationship Rules", index=False)
            st.download_button("Download complete scenario workbook", out.getvalue(), "systems_thinking_scenarios.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
            all_long = []
            for sc,obj in scenarios.items():
                df = obj["result"].copy(); df["Scenario"] = sc; all_long.append(df)
            st.download_button("Download all trajectories (CSV)", pd.concat(all_long,ignore_index=True).to_csv(index=False).encode(), "all_scenario_trajectories.csv", "text/csv")

# ---------- Save project ----------
st.divider()
st.header("Save this project")
st.caption("The project is saved privately to the signed-in account. Only your account can access its saved rows through the database policies.")
current_matrix = matrix_from_payload(st.session_state.asis_matrix_payload)
current_payload = {
    "problem": st.session_state.get("problem_statement", payload.get("problem", "")),
    "asis_matrix": matrix_to_payload(current_matrix) if current_matrix is not None else None,
    "initial_values": st.session_state.get("initial_values_payload") or {},
    "variable_descriptions": (st.session_state.get("variable_descriptions_editor").fillna("").to_dict("records") if isinstance(st.session_state.get("variable_descriptions_editor"), pd.DataFrame) else payload.get("variable_descriptions", [])),
    "interventions": st.session_state.get("interventions_payload", []),
    "relationship_rules": st.session_state.get("rules_payload", []),
    "steps": st.session_state.get("simulation_settings", {}).get("steps", payload.get("steps",10)),
    "dt": st.session_state.get("simulation_settings", {}).get("dt", payload.get("dt",1.0)),
}
sc1,sc2 = st.columns([2,1])
with sc1:
    if st.button("Save project to my account", type="primary", use_container_width=True):
        try:
            row = {"user_id":uid,"name":st.session_state.project_name.strip() or "Untitled project","payload":current_payload,"updated_at":datetime.now(timezone.utc).isoformat()}
            if st.session_state.project_id:
                sb.table("projects").update(row).eq("id",st.session_state.project_id).eq("user_id",uid).execute()
            else:
                response = sb.table("projects").insert(row).execute()
                if response.data: st.session_state.project_id = response.data[0]["id"]
            st.session_state.project_payload = current_payload
            st.success("Project saved to your individual account.")
            st.rerun()
        except Exception as exc:
            st.error(f"Could not save project: {exc}. Confirm the new Supabase schema has been installed.")
with sc2:
    if st.button("Run professor formula check", use_container_width=True):
        baseline_check = validate_reference_first_iteration()
        intervention_check = validate_reference_intervention()
        passed = baseline_check["passed"] and intervention_check["passed_first_intervention_step"] and intervention_check["passed_beetle_activation_t4"] and intervention_check["passed_t4_to_t5_reference"]
        if passed:
            st.success("All checks passed: baseline first iteration, intervention first iteration, beetle activation at T4, and T4→T5 results match the professor workbook within tolerance.")
        else:
            st.error("At least one reference check failed. Do not rely on the simulation until the discrepancy is resolved.")
        st.json({"baseline":baseline_check,"intervention":intervention_check})
