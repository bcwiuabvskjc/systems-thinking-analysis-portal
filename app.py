from __future__ import annotations
import io, json, os
from pathlib import Path
import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st
from analysis_core import (
    KSIM_FORMULA, authenticate_user, register_user, init_db, save_project,
    list_projects, load_project, delete_project, run_ksim_course,
    make_state_frame, make_calculation_frame, validate_model,
)

st.set_page_config(page_title="Systems Thinking & KSIM Studio", page_icon="🧭", layout="wide")
st.markdown("""
<style>
.block-container {padding-top:1.15rem; padding-bottom:2.5rem; max-width:1600px}
.hero {padding:1.15rem 1.45rem;border-radius:14px;background:linear-gradient(120deg,#10263c,#245b78);color:white;margin-bottom:1rem}
.hero h1 {color:white;margin:0;font-size:1.8rem}.hero p {color:#e2edf5;margin:.35rem 0 0}
[data-testid="stMetric"] {background:rgba(120,140,160,.08);padding:.7rem;border-radius:10px}
</style>
<div class="hero"><h1>Systems Thinking & KSIM Studio</h1><p>Entity–attribute modelling · Course-aligned KSIM calculations · Intervention comparison · Private projects</p></div>
""", unsafe_allow_html=True)

init_db()

# ----------- Demo model, taken from the user's supplied professor workbook screenshots -----------
def professor_example():
    variables = pd.DataFrame([
        {"Code":"x1", "Entity":"Parthenium", "Relevant attribute":"Abundance of Parthenium", "Initial value":0.500, "Start time":0},
        {"Code":"x2", "Entity":"City People", "Relevant attribute":"Incidence of Asthma in City People", "Initial value":0.350, "Start time":0},
        {"Code":"x3", "Entity":"City People", "Relevant attribute":"Happiness Level", "Initial value":0.350, "Start time":0},
        {"Code":"x4", "Entity":"Government", "Relevant attribute":"Seriousness for Parthenium Eradication", "Initial value":0.300, "Start time":0},
        {"Code":"x5", "Entity":"Hospitals", "Relevant attribute":"No. of Admitted Asthma Patients", "Initial value":0.300, "Start time":0},
        {"Code":"x6", "Entity":"Expert Committee", "Relevant attribute":"Involvement of Expert Committee", "Initial value":0.100, "Start time":0},
        {"Code":"x7", "Entity":"Beetle", "Relevant attribute":"No. of Beetle", "Initial value":0.300, "Start time":4},
    ])
    codes = variables["Code"].tolist()
    A = np.array([
        [ 0.30,  0.00,  0.00, -0.10,  0.00,  0.00, -0.90],
        [ 0.70, -0.20, -0.20, -0.30,  0.00, -0.10,  0.00],
        [-0.70, -0.80,  0.40,  0.10, -0.70,  0.00,  0.10],
        [ 0.60,  0.70, -0.50, -0.20,  0.50,  0.60, -0.30],
        [ 0.70,  0.30, -0.10, -0.10, -0.20, -0.10,  0.00],
        [ 0.50,  0.50, -0.50,  0.70,  0.60,  0.50, -0.30],
        [ 0.00,  0.00,  0.00,  0.00,  0.00,  0.00,  0.50],
    ], dtype=float)
    matrix = pd.DataFrame(A, index=codes, columns=codes)
    return variables, matrix


def df_json(df: pd.DataFrame) -> list:
    return json.loads(df.to_json(orient="records", double_precision=15))


def current_payload():
    return {
        "schema_version": 2,
        "variables": df_json(st.session_state.model_variables),
        "matrix_codes": list(st.session_state.model_matrix.index.astype(str)),
        "matrix": st.session_state.model_matrix.to_numpy(float).tolist(),
        "simulation_steps": int(st.session_state.get("steps", 11)),
        "dt": float(st.session_state.get("dt", 1.0)),
    }


def apply_payload(payload: dict):
    vars_df = pd.DataFrame(payload["variables"])
    expected = ["Code", "Entity", "Relevant attribute", "Initial value", "Start time"]
    for col in expected:
        if col not in vars_df:
            vars_df[col] = 0 if col in ("Initial value", "Start time") else ""
    vars_df = vars_df[expected]
    codes = vars_df["Code"].astype(str).tolist()
    mat = np.asarray(payload.get("matrix", np.zeros((len(codes), len(codes)))), dtype=float)
    matrix = pd.DataFrame(mat, index=codes, columns=codes)
    st.session_state.model_variables = vars_df
    st.session_state.model_matrix = matrix
    st.session_state.matrix_revision = st.session_state.get("matrix_revision", 0) + 1
    st.session_state.steps = int(payload.get("simulation_steps", 11))
    st.session_state.dt = float(payload.get("dt", 1.0))
    st.session_state.pop("latest_run", None)
    st.session_state.pop("latest_comparison", None)


def clear_run():
    st.session_state.pop("latest_run", None)
    st.session_state.pop("latest_comparison", None)


def login_screen():
    st.subheader("Sign in to your private workspace")
    st.write("Projects are scoped to the signed-in account. Other users cannot open or delete your saved projects through the portal's project controls.")
    login_tab, register_tab = st.tabs(["Sign in", "Create account"])
    with login_tab:
        with st.form("login_form"):
            username = st.text_input("Username", key="login_username")
            password = st.text_input("Password", type="password", key="login_password")
            submit = st.form_submit_button("Sign in", type="primary", use_container_width=True)
        if submit:
            user = authenticate_user(username, password)
            if user:
                st.session_state.auth_user = user
                st.rerun()
            else:
                st.error("Incorrect username or password.")
    with register_tab:
        st.info("Create a unique username and a password of at least 10 characters. This starter version does not verify email addresses.")
        with st.form("register_form"):
            new_user = st.text_input("Choose username", key="register_username")
            new_pass = st.text_input("Choose password", type="password", key="register_password")
            confirm = st.text_input("Confirm password", type="password", key="register_confirm")
            submit_reg = st.form_submit_button("Create account", type="primary", use_container_width=True)
        if submit_reg:
            if new_pass != confirm:
                st.error("The passwords do not match.")
            else:
                try:
                    register_user(new_user, new_pass)
                    st.success("Account created. Sign in using the Sign in tab.")
                except Exception as exc:
                    st.error(str(exc))
    st.divider()
    st.caption("Hosting note: this ZIP uses a local SQLite database. For durable multi-user hosting, configure a persistent disk or managed database; see the included README before relying on it for important projects.")

if "auth_user" not in st.session_state:
    st.session_state.auth_user = None
if not st.session_state.auth_user:
    login_screen()
    st.stop()

user = st.session_state.auth_user
if "model_variables" not in st.session_state:
    v, m = professor_example()
    st.session_state.model_variables = v
    st.session_state.model_matrix = m
    st.session_state.matrix_revision = 0
    st.session_state.steps = 11
    st.session_state.dt = 1.0
    st.session_state.project_name = "Parthenium — professor example"

# ----------- Sidebar: private project controls -----------
with st.sidebar:
    st.markdown(f"### Signed in as `{user['username']}`")
    if st.button("Sign out", use_container_width=True):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()
    st.divider()
    st.subheader("My private projects")
    projects = list_projects(user["id"])
    if projects:
        labels = {f"{p['name']} · {p['updated_at']}": p for p in projects}
        chosen_label = st.selectbox("Saved project", list(labels), key="saved_project_select")
        chosen = labels[chosen_label]
        c_load, c_delete = st.columns(2)
        if c_load.button("Open", use_container_width=True):
            try:
                name, payload, _ = load_project(user["id"], chosen["id"])
                apply_payload(payload)
                st.session_state.project_name = name
                st.success(f"Opened {name}")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
        if c_delete.button("Delete", use_container_width=True):
            st.session_state.confirm_delete_project_id = chosen["id"]
        if st.session_state.get("confirm_delete_project_id") == chosen["id"]:
            st.warning(f"Delete **{chosen['name']}** permanently from your account?")
            d1, d2 = st.columns(2)
            if d1.button("Confirm delete", type="primary"):
                try:
                    delete_project(user["id"], chosen["id"])
                    st.session_state.pop("confirm_delete_project_id", None)
                    st.success("Project deleted from your account.")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
            if d2.button("Cancel"):
                st.session_state.pop("confirm_delete_project_id", None)
                st.rerun()
    else:
        st.caption("You have no saved projects yet.")
    st.divider()
    st.caption("Saving is account-specific. Sharing the public app URL does not share your project records.")

# ----------- Project import / save / demo -----------
st.subheader("Project")
pcol1, pcol2, pcol3, pcol4 = st.columns([2, 1, 1, 1])
with pcol1:
    st.session_state.project_name = st.text_input("Project name", value=st.session_state.get("project_name", "My KSIM project"), key="project_name_input")
with pcol2:
    if st.button("Save to my account", type="primary", use_container_width=True):
        try:
            save_project(user["id"], st.session_state.project_name, current_payload())
            st.success("Saved privately to your account.")
        except Exception as exc:
            st.error(str(exc))
with pcol3:
    backup = json.dumps(current_payload(), indent=2, ensure_ascii=False).encode("utf-8")
    st.download_button("Download JSON", backup, file_name="ksim_project_backup.json", mime="application/json", use_container_width=True)
with pcol4:
    if st.button("Reset to professor example", use_container_width=True):
        v, m = professor_example()
        st.session_state.model_variables = v
        st.session_state.model_matrix = m
        st.session_state.matrix_revision += 1
        st.session_state.project_name = "Parthenium — professor example"
        st.session_state["project_name_input"] = "Parthenium — professor example"
        clear_run()
        st.rerun()

with st.expander("Import a JSON project backup"):
    json_upload = st.file_uploader("Choose a previously exported KSIM JSON file", type=["json"], key="json_restore")
    if json_upload is not None and st.button("Restore JSON backup", key="restore_json_button"):
        try:
            payload = json.load(json_upload)
            apply_payload(payload)
            st.session_state.project_name = "Restored project"
            st.session_state["project_name_input"] = "Restored project"
            st.success("Project restored. Save it to your account to keep it in your private project list.")
            st.rerun()
        except Exception as exc:
            st.error(f"Could not restore this JSON file: {exc}")

st.divider()

# ----------- Model definition -----------
st.header("1 · Entities and relevant attributes")
st.write("An **entity** is the actor or object in the system. A **relevant attribute** is the state/characteristic being simulated. Each attribute gets its own code (x1, x2, …) and one row in the matrix.")
add_col, import_col, template_col = st.columns([1, 2, 2])
with add_col:
    if st.button("＋ Add variable", type="primary", use_container_width=True):
        old_v = st.session_state.model_variables.copy()
        old_m = st.session_state.model_matrix.copy()
        new_idx = len(old_v) + 1
        new_code = f"x{new_idx}"
        while new_code in old_v["Code"].astype(str).tolist():
            new_idx += 1; new_code = f"x{new_idx}"
        new_row = {"Code":new_code,"Entity":"New entity","Relevant attribute":"New relevant attribute","Initial value":0.5,"Start time":0}
        st.session_state.model_variables = pd.concat([old_v, pd.DataFrame([new_row])], ignore_index=True)
        new_codes = st.session_state.model_variables["Code"].astype(str).tolist()
        expanded = pd.DataFrame(0.0, index=new_codes, columns=new_codes)
        for r in old_m.index:
            for c in old_m.columns:
                expanded.loc[str(r), str(c)] = float(old_m.loc[r, c])
        st.session_state.model_matrix = expanded
        st.session_state.matrix_revision += 1
        clear_run()
        st.rerun()
with import_col:
    var_upload = st.file_uploader("Import variables CSV", type=["csv"], key="variables_csv_upload", help="Required columns: Code, Entity, Relevant attribute, Initial value. Optional: Start time.")
    if var_upload is not None and st.button("Import variables", key="import_variables_button"):
        try:
            imported = pd.read_csv(var_upload)
            rename_map = {c.lower().strip(): c for c in imported.columns}
            def find_col(*names):
                for name in names:
                    if name in rename_map: return rename_map[name]
                return None
            c_code=find_col("code","variable code"); c_ent=find_col("entity"); c_attr=find_col("relevant attribute","attribute","variable","name")
            c_init=find_col("initial value","initial","t=0","t0"); c_start=find_col("start time","start","introduced at")
            if not all([c_code,c_ent,c_attr,c_init]): raise ValueError("CSV must include Code, Entity, Relevant attribute, and Initial value columns.")
            newv=pd.DataFrame({"Code":imported[c_code].astype(str),"Entity":imported[c_ent].astype(str),"Relevant attribute":imported[c_attr].astype(str),"Initial value":pd.to_numeric(imported[c_init],errors="raise"),"Start time":pd.to_numeric(imported[c_start],errors="raise").fillna(0).astype(int) if c_start else 0})
            codes=newv["Code"].tolist()
            st.session_state.model_variables=newv
            st.session_state.model_matrix=pd.DataFrame(0.0,index=codes,columns=codes)
            st.session_state.matrix_revision += 1
            clear_run(); st.success("Variables imported. Please import or fill the cross-impact matrix next."); st.rerun()
        except Exception as exc: st.error(f"Could not import variables: {exc}")
with template_col:
    template = pd.DataFrame([{ "Code":"x1","Entity":"Entity name","Relevant attribute":"Attribute being simulated","Initial value":0.5,"Start time":0},{"Code":"x2","Entity":"Another entity","Relevant attribute":"Another attribute","Initial value":0.35,"Start time":0}])
    st.download_button("Download variables CSV template", template.to_csv(index=False).encode(), "variables_template.csv", "text/csv", use_container_width=True)

# Stable editor key changes when variables are added/imported, avoiding stale grid shapes.
var_key = f"variables_editor_{len(st.session_state.model_variables)}_{st.session_state.matrix_revision}"
editable_vars = st.data_editor(
    st.session_state.model_variables,
    key=var_key,
    num_rows="dynamic",
    hide_index=True,
    use_container_width=True,
    column_config={
        "Code": st.column_config.TextColumn("Variable code", help="Unique ID used by the cross-impact matrix"),
        "Entity": st.column_config.TextColumn("Entity"),
        "Relevant attribute": st.column_config.TextColumn("Relevant attribute / variable"),
        "Initial value": st.column_config.NumberColumn("Initial state (0–1)", min_value=0.0, max_value=1.0, step=0.01, format="%.5f"),
        "Start time": st.column_config.NumberColumn("Introduced at T", min_value=0, max_value=200, step=1),
    },
)
if not editable_vars.equals(st.session_state.model_variables):
    old_codes = st.session_state.model_variables["Code"].astype(str).tolist()
    edited = editable_vars.copy()
    edited["Code"] = edited["Code"].astype(str).str.strip()
    new_codes = edited["Code"].tolist()
    old_matrix = st.session_state.model_matrix.copy()
    # preserve matrix values for codes retained; new codes get zeros.
    expanded = pd.DataFrame(0.0, index=new_codes, columns=new_codes)
    for r in new_codes:
        for c in new_codes:
            if r in old_matrix.index and c in old_matrix.columns:
                expanded.loc[r,c] = old_matrix.loc[r,c]
    st.session_state.model_variables = edited.reset_index(drop=True)
    st.session_state.model_matrix = expanded
    st.session_state.matrix_revision += 1
    clear_run()
    st.rerun()

st.caption("State values and matrix impacts use the 0–1 state scale and the impact coefficients you provide. Variables with Start time = T4 remain absent before T4, then enter at their initial value.")

st.header("2 · Cross-impact matrix")
st.write("Rows are target attributes (i); columns are influencing/source attributes (j), matching the supplied KSIM equation. A positive coefficient contributes to the denominator; a negative coefficient contributes to the numerator.")
mat_codes = st.session_state.model_variables["Code"].astype(str).tolist()
curmat = st.session_state.model_matrix.copy().reindex(index=mat_codes, columns=mat_codes, fill_value=0.0)
mc1, mc2 = st.columns([2, 2])
with mc1:
    mat_upload = st.file_uploader("Optional: import square matrix CSV", type=["csv"], key="matrix_csv_upload")
    if mat_upload is not None and st.button("Import matrix CSV", key="import_matrix_button"):
        try:
            raw = pd.read_csv(mat_upload, index_col=0)
            raw.index = raw.index.astype(str); raw.columns = raw.columns.astype(str)
            raw = raw.apply(pd.to_numeric, errors="raise")
            if raw.shape != (len(mat_codes),len(mat_codes)) or list(raw.index) != mat_codes or list(raw.columns) != mat_codes:
                raise ValueError("Matrix CSV must be square and use the same variable codes in the same order as the variable table.")
            st.session_state.model_matrix=raw
            st.session_state.matrix_revision += 1
            clear_run(); st.success("Matrix imported."); st.rerun()
        except Exception as exc: st.error(f"Could not import matrix: {exc}")
with mc2:
    mat_template = curmat.copy(); mat_template.insert(0,"Variable code",mat_template.index)
    st.download_button("Download matrix CSV template",mat_template.to_csv(index=False).encode(),"cross_impact_matrix_template.csv","text/csv",use_container_width=True)
mat_key = f"matrix_editor_{len(mat_codes)}_{st.session_state.matrix_revision}"
editable_matrix = st.data_editor(curmat, key=mat_key, use_container_width=True, num_rows="fixed", column_config={c:st.column_config.NumberColumn(c,format="%.4f") for c in mat_codes})
if not editable_matrix.equals(curmat):
    st.session_state.model_matrix = editable_matrix.apply(pd.to_numeric,errors="coerce").reindex(index=mat_codes,columns=mat_codes)
    st.session_state.matrix_revision += 1
    clear_run()
    st.rerun()

# ----------- Simulation settings and interventions -----------
st.header("3 · KSIM simulation")
st.latex(r"x_i(t+\Delta t)=x_i(t)^{p_i(t)}")
st.latex(r"p_i(t)=\frac{1+\frac{\Delta t}{2}\sum_{j=1}^{N}(|a_{ij}|-a_{ij})x_j(t)}{1+\frac{\Delta t}{2}\sum_{j=1}^{N}(|a_{ij}|+a_{ij})x_j(t)}")
st.caption("This is the formula shown in the supplied course reference. Δt defaults to 1. Exponents are calculated for each active attribute at T0, T1, …; the resulting state is shown at the next time point.")
sc1, sc2, sc3 = st.columns(3)
with sc1:
    steps = st.number_input("Final time period", min_value=1, max_value=200, value=int(st.session_state.get("steps",11)), step=1, key="steps")
with sc2:
    dt = st.number_input("Δt", min_value=0.01, max_value=5.0, value=float(st.session_state.get("dt",1.0)), step=0.1, key="dt")
with sc3:
    st.metric("Number of attributes", len(st.session_state.model_variables))

st.subheader("Optional intervention scenario")
st.write("Add an intervention to set an attribute to a new 0–1 value at a selected time. The portal runs the original baseline and the intervention scenario separately, then compares them.")
intervention_seed = pd.DataFrame(columns=["Variable code", "Time", "Set value"])
interventions = st.data_editor(
    intervention_seed, num_rows="dynamic", hide_index=True,
    use_container_width=True,
    column_config={
        "Variable code": st.column_config.SelectboxColumn("Attribute to intervene on", options=mat_codes, required=True),
        "Time": st.column_config.NumberColumn("At time T", min_value=0, max_value=int(steps), step=1, required=True),
        "Set value": st.column_config.NumberColumn("Set state (0–1)", min_value=0.0, max_value=1.0, step=0.01, required=True, format="%.5f"),
    },
    key="intervention_editor",
)
run1, run2 = st.columns([1, 3])
with run1:
    run_clicked = st.button("Run simulation", type="primary", use_container_width=True)
with run2:
    st.caption("The graph plots state values over time, not exponents. Exponents and their numerator/denominator are shown in the calculation table below.")

if run_clicked:
    try:
        current_vars = st.session_state.model_variables.copy().reset_index(drop=True)
        current_mat = st.session_state.model_matrix.copy().reindex(index=current_vars["Code"].astype(str), columns=current_vars["Code"].astype(str))
        current_vars["Initial value"] = pd.to_numeric(current_vars["Initial value"], errors="raise")
        current_vars["Start time"] = pd.to_numeric(current_vars["Start time"], errors="raise").astype(int)
        validate_model(current_vars, current_mat)
        if (current_vars["Start time"] > int(steps)).any():
            raise ValueError("A variable's Start time cannot be later than the selected final time period.")
        state, exp, nums, dens = run_ksim_course(current_vars, current_mat, int(steps), float(dt))
        st.session_state.latest_run = {"variables":current_vars,"matrix":current_mat,"states":state,"exponents":exp,"numerators":nums,"denominators":dens,"steps":int(steps),"dt":float(dt)}
        # Intervention comparison is optional. Empty rows are ignored.
        valid_interventions = interventions.dropna(subset=["Variable code","Time","Set value"]).copy() if len(interventions) else pd.DataFrame()
        if not valid_interventions.empty:
            valid_interventions["Time"] = valid_interventions["Time"].astype(int)
            state_i, exp_i, nums_i, dens_i = run_ksim_course(current_vars, current_mat, int(steps), float(dt), valid_interventions)
            st.session_state.latest_comparison = {"states":state_i,"exponents":exp_i,"numerators":nums_i,"denominators":dens_i,"interventions":valid_interventions}
        else:
            st.session_state.pop("latest_comparison", None)
        st.success("Simulation completed using the course formula.")
    except Exception as exc:
        st.error(f"Simulation could not run: {exc}")

result = st.session_state.get("latest_run")
if result:
    vars_run = result["variables"]
    state = result["states"]
    exp = result["exponents"]
    nums = result["numerators"]
    dens = result["denominators"]
    steps_run = result["steps"]
    state_frame = make_state_frame(vars_run, state)
    st.header("4 · Results — state values by time")
    st.caption("The table follows the workbook layout: entity, relevant attribute, code, then T0, T1, T2, …")
    state_format = {c: st.column_config.NumberColumn(c, format="%.3f") for c in state_frame.columns if c.startswith("T")}
    st.dataframe(state_frame, use_container_width=True, hide_index=True, height=360, column_config=state_format)
    st.download_button("Download state results CSV", state_frame.to_csv(index=False).encode("utf-8"), "KSIM_State_Results.csv", "text/csv")

    options = {f"{r['Code']} — {r['Relevant attribute']} ({r['Entity']})": r["Code"] for _,r in vars_run.iterrows()}
    selected_labels = st.multiselect("Choose attributes to plot together", options=list(options), default=list(options)[:min(4,len(options))], key="plot_selection")
    selected_codes = [options[x] for x in selected_labels]
    time_labels = [f"T{t}" for t in range(steps_run+1)]
    plot_rows=[]
    for i, row in vars_run.iterrows():
        if row["Code"] not in selected_codes: continue
        for t, time_label in enumerate(time_labels):
            plot_rows.append({"Time":time_label,"Time index":t,"Attribute":f"{row['Code']} — {row['Relevant attribute']}","State value":state[t,i]})
    plot_df = pd.DataFrame(plot_rows)
    st.subheader("Behaviour-over-time graph")
    if not plot_df.empty:
        fig = px.line(plot_df, x="Time", y="State value", color="Attribute", markers=True, category_orders={"Time":time_labels}, title="KSIM state trajectories (0–1 scale)")
        fig.update_yaxes(range=[0,1], title="State value (0–1)")
        fig.update_xaxes(title="Time period")
        fig.update_layout(legend_title_text="Relevant attribute", hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Select at least one attribute to display the graph.")

    comparison = st.session_state.get("latest_comparison")
    if comparison:
        st.subheader("Baseline vs intervention comparison")
        comp_rows=[]
        for i,row in vars_run.iterrows():
            if row["Code"] not in selected_codes: continue
            for t, time_label in enumerate(time_labels):
                comp_rows.append({"Time":time_label,"Attribute":f"{row['Code']} — {row['Relevant attribute']}","Scenario":"Baseline","State value":state[t,i]})
                comp_rows.append({"Time":time_label,"Attribute":f"{row['Code']} — {row['Relevant attribute']}","Scenario":"Intervention","State value":comparison["states"][t,i]})
        comp_df=pd.DataFrame(comp_rows)
        figc=px.line(comp_df,x="Time",y="State value",color="Attribute",line_dash="Scenario",markers=True,category_orders={"Time":time_labels},title="Baseline vs intervention")
        figc.update_yaxes(range=[0,1],title="State value (0–1 scale)")
        figc.update_layout(hovermode="x unified")
        st.plotly_chart(figc,use_container_width=True)
        st.caption("An intervention changes the selected state at the chosen time; subsequent periods are recalculated using the same KSIM formula.")
        comp_state = make_state_frame(vars_run, comparison["states"])
        st.dataframe(comp_state, use_container_width=True, hide_index=True)

    st.header("5 · Inspect calculated KSIM exponents")
    calc_frame = make_calculation_frame(vars_run, nums, dens, exp)
    st.caption("For every active variable and time point, the table shows the numerator, denominator, and exponent Pᵢ(t), in the same order as the professor's calculation sheet. Inactive variables remain blank until their Start time.")
    calc_format = {c: st.column_config.NumberColumn(c, format="%.5f") for c in calc_frame.columns if "Pᵢ" in c}
    st.dataframe(calc_frame, use_container_width=True, hide_index=True, height=420, column_config=calc_format)
    st.download_button("Download detailed KSIM calculations CSV", calc_frame.to_csv(index=False).encode("utf-8"), "KSIM_Detailed_Calculations.csv", "text/csv")
    with st.expander("Cross-impact matrix used for this run"):
        st.dataframe(result["matrix"], use_container_width=True)

    # Excel export with workbook-like tables
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
        output=io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            state_frame.to_excel(writer,sheet_name="State Results",index=False)
            result["matrix"].rename_axis("Target code").to_excel(writer,sheet_name="Cross Impact Matrix")
            calc_frame.to_excel(writer,sheet_name="KSIM Calculations",index=False)
            vars_run.to_excel(writer,sheet_name="Variables",index=False)
            if comparison:
                make_state_frame(vars_run,comparison["states"]).to_excel(writer,sheet_name="Intervention Results",index=False)
        output.seek(0)
        wb=__import__("openpyxl").load_workbook(output)
        for ws in wb.worksheets:
            ws.freeze_panes="A2"; ws.sheet_view.showGridLines=False
            if ws.max_row>1: ws.auto_filter.ref=ws.dimensions
            for cell in ws[1]:
                cell.font=Font(bold=True,color="FFFFFF")
                cell.fill=PatternFill("solid",fgColor="17365D")
                cell.alignment=Alignment(vertical="center",wrap_text=True)
            for col in ws.columns:
                width=max((min(len(str(c.value or "")),42) for c in list(col)[:150]),default=12)
                ws.column_dimensions[get_column_letter(col[0].column)].width=max(12,width+2)
        final=io.BytesIO(); wb.save(final)
        st.download_button("Download complete Excel report",final.getvalue(),"KSIM_Complete_Report.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",type="primary")
    except Exception as exc:
        st.warning(f"Excel export could not be prepared: {exc}")

st.header("6 · Cross-impact influence and dependence")
if result:
    A=result["matrix"]
    metrics=pd.DataFrame({"Code":A.index,"Entity":vars_run["Entity"].tolist(),"Relevant attribute":vars_run["Relevant attribute"].tolist(),"Influence (row sum)":A.sum(axis=1).values,"Dependence (column sum)":A.sum(axis=0).values})
    st.dataframe(metrics,use_container_width=True,hide_index=True)
    figm=px.scatter(metrics,x="Dependence (column sum)",y="Influence (row sum)",text="Code",hover_data=["Entity","Relevant attribute"],title="Influence vs dependence")
    st.plotly_chart(figm,use_container_width=True)

st.divider()
st.caption("Privacy and persistence: saved project queries are restricted to the signed-in user ID, and passwords are stored as salted PBKDF2 hashes. This is an application-level login, not an enterprise identity provider. SQLite on ephemeral hosting may be reset; configure persistent storage or a managed database before using it as the sole copy of important work. Export JSON backups regularly.")
