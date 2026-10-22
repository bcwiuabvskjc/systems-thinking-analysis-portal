from __future__ import annotations

import io
import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from analysis_core import (
    validate_dataframe, coerce_numeric, detect_cross_impact,
    cross_impact_metrics, run_ksim, KSIM_METHOD
)

st.set_page_config(page_title="Systems Thinking Studio", page_icon="🧭", layout="wide")

# A local SQLite database is durable across ordinary app reruns. On hosted platforms,
# check the platform's filesystem persistence policy before treating it as long-term storage.
DB_PATH = Path(__file__).with_name("systems_thinking_projects.db")

st.markdown("""
<style>
.block-container {padding-top:1.2rem;padding-bottom:3rem;max-width:1450px}
.hero {padding:1.45rem 1.7rem;border-radius:18px;background:linear-gradient(120deg,#10243a,#236b78);color:white;margin-bottom:1.1rem}
.hero h1 {color:white;margin:0;font-size:2rem}.hero p {color:#e2edf1;margin:.45rem 0 0}
.step-pill {border:1px solid #d8e2ea;border-radius:12px;padding:.7rem .85rem;background:#f8fafc}
.small-muted {color:#64748b;font-size:.9rem}
div[data-testid="stMetric"] {border:1px solid #e2e8f0;padding:12px;border-radius:12px;background:#fbfdff}
</style>
<div class="hero"><h1>Systems Thinking Studio</h1>
<p>A guided workspace to build, simulate, save and compare systems-thinking models.</p></div>
""", unsafe_allow_html=True)

# ---------- durable project storage ----------
def connect_db():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            payload TEXT NOT NULL
        )
    """)
    con.commit()
    return con

def list_projects():
    with connect_db() as con:
        return con.execute("SELECT id, name, updated_at FROM projects ORDER BY updated_at DESC").fetchall()

def save_project(project):
    project["updated_at"] = datetime.now().isoformat(timespec="seconds")
    with connect_db() as con:
        con.execute(
            "INSERT INTO projects (id, name, updated_at, payload) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET name=excluded.name, updated_at=excluded.updated_at, payload=excluded.payload",
            (project["id"], project["name"], project["updated_at"], json.dumps(project, allow_nan=False))
        )
        con.commit()

def load_project(project_id):
    with connect_db() as con:
        row = con.execute("SELECT payload FROM projects WHERE id=?", (project_id,)).fetchone()
    return json.loads(row[0]) if row else None

def delete_project(project_id):
    with connect_db() as con:
        con.execute("DELETE FROM projects WHERE id=?", (project_id,))
        con.commit()

# ---------- project defaults and session state ----------
def new_project(name="Untitled KSIM project"):
    variables = ["Parthenium", "Asthma incidence", "Happiness", "Government response", "Hospital admissions", "Expert committee"]
    initial = [0.50, 0.35, 0.35, 0.30, 0.30, 0.10]
    A = np.array([
        [0.3, 0, 0, -0.1, 0, 0],
        [0.7, -0.2, -0.2, -0.3, 0, -0.1],
        [0, -0.8, 0.4, 0.1, -0.7, 0],
        [0.6, 0.7, -0.5, -0.2, 0.5, 0.6],
        [0.7, 0.3, -0.1, -0.1, -0.2, -0.1],
        [0.5, 0.5, -0.5, 0.7, 0.6, 0.5],
    ])
    matrix = pd.DataFrame(A, index=variables, columns=variables)
    return {
        "id": str(uuid.uuid4()), "name": name, "updated_at": "",
        "step": 1, "variables": variables, "initial": initial,
        "matrix": matrix.to_dict(orient="split"), "steps": 10, "dt": 1.0,
        "results": None, "exponents": None, "scenarios": []
    }

def matrix_from_project(project):
    d = project["matrix"]
    return pd.DataFrame(d["data"], index=d["index"], columns=d["columns"], dtype=float)

if "project" not in st.session_state:
    st.session_state.project = None
if "page" not in st.session_state:
    st.session_state.page = "home"

def go(page):
    st.session_state.page = page

def persist_current(show_message=True):
    if st.session_state.project:
        save_project(st.session_state.project)
        if show_message:
            st.toast("Project saved.", icon="✅")

# ---------- sidebar ----------
with st.sidebar:
    st.markdown("## Workspace")
    st.caption("Build a model one step at a time.")
    if st.session_state.project:
        st.info(f"Current project\n\n**{st.session_state.project['name']}**")
        if st.button("Save project", use_container_width=True, type="primary"):
            persist_current()
        if st.button("Project dashboard", use_container_width=True):
            go("home")
            st.rerun()
    st.divider()
    st.caption("KSIM convention: rows are targets; columns are sources.")
    st.caption("Avoid uploading confidential or personally identifying information.")

# ---------- home / project dashboard ----------
if st.session_state.page == "home":
    st.subheader("Your projects")
    st.write("Create a new model or reopen a saved project to continue where you left off.")
    left, right = st.columns([1.3, 1])
    with left:
        with st.form("new_project_form", clear_on_submit=True):
            project_name = st.text_input("New project name", value="Parthenium KSIM model")
            submitted = st.form_submit_button("＋ Create project", type="primary", use_container_width=True)
        if submitted:
            p = new_project(project_name.strip() or "Untitled KSIM project")
            st.session_state.project = p
            st.session_state.page = "builder"
            persist_current(False)
            st.rerun()
    with right:
        st.markdown("#### Start with a course example")
        if st.button("Load Parthenium teaching example", use_container_width=True):
            st.session_state.project = new_project("Parthenium — AS-IS")
            st.session_state.page = "builder"
            persist_current(False)
            st.rerun()

    st.divider()
    projects = list_projects()
    if not projects:
        st.info("No saved projects yet. Create one above; it will appear here.")
    else:
        for pid, pname, updated in projects:
            c1, c2, c3 = st.columns([3, 1.2, 1])
            c1.markdown(f"**{pname}**")
            c1.caption(f"Last saved: {updated.replace('T', ' ')}")
            if c2.button("Open", key=f"open_{pid}", use_container_width=True):
                st.session_state.project = load_project(pid)
                st.session_state.page = "builder"
                st.rerun()
            if c3.button("Delete", key=f"delete_{pid}", use_container_width=True):
                delete_project(pid)
                st.rerun()
    st.caption("Storage note: this version uses a SQLite database file beside the app. For hosted deployments, long-term persistence across rebuilds/restarts depends on the host's filesystem; a managed database is the production-safe next step.")
    st.stop()

# ---------- project builder ----------
project = st.session_state.project
if project is None:
    go("home")
    st.rerun()

# reload project reference after any saved/open operation
project = st.session_state.project
step_labels = ["Variables", "Cross-impact matrix", "Simulation settings", "Run & results"]
st.markdown(f"### {project['name']}")
top1, top2 = st.columns([4, 1])
with top1:
    st.progress(int(project.get("step", 1)) / len(step_labels), text=f"Step {project.get('step', 1)} of {len(step_labels)} · {step_labels[min(project.get('step',1)-1,3)]}")
with top2:
    if st.button("Save now", use_container_width=True):
        persist_current()

tabs = st.columns(4)
for idx, label in enumerate(step_labels, start=1):
    with tabs[idx-1]:
        if idx == project.get("step", 1):
            st.markdown(f"**➡️ {idx}. {label}**")
        else:
            st.markdown(f"<span class='small-muted'>{idx}. {label}</span>", unsafe_allow_html=True)

if project.get("step", 1) == 1:
    st.subheader("Step 1 · Define variables")
    st.write("Each variable represents an attribute in your system. Initial values in the course workbook are normalized between 0 and 1.")
    names_text = st.text_area("Variable names — one per line", value="\n".join(project["variables"]), height=170)
    current_names = [x.strip() for x in names_text.splitlines() if x.strip()]
    if current_names and current_names != project["variables"]:
        old_names = project["variables"]
        old_A = matrix_from_project(project)
        old_initial = dict(zip(old_names, project["initial"]))
        new_A = pd.DataFrame(0.0, index=current_names, columns=current_names)
        for r in current_names:
            for c in current_names:
                if r in old_A.index and c in old_A.columns:
                    new_A.loc[r, c] = float(old_A.loc[r, c])
        project["variables"] = current_names
        project["initial"] = [float(old_initial.get(n, 0.5)) for n in current_names]
        project["matrix"] = new_A.to_dict(orient="split")
        project["results"] = None
    if len(current_names) < 2 or len(current_names) > 20 or len(set(current_names)) != len(current_names):
        st.error("Use 2–20 unique variable names.")
    init_df = pd.DataFrame({"Variable": project["variables"], "Initial state (0–1)": project["initial"]})
    edited_init = st.data_editor(init_df, use_container_width=True, hide_index=True, disabled=["Variable"], key="initial_editor")
    try:
        initial_vals = pd.to_numeric(edited_init["Initial state (0–1)"], errors="raise").astype(float).tolist()
        if any(not np.isfinite(v) or v < 0 or v > 1 for v in initial_vals):
            st.error("Every initial state must be between 0 and 1.")
        else:
            project["initial"] = initial_vals
    except Exception:
        st.error("Initial states must be numeric.")
    if st.button("Continue to matrix →", type="primary", use_container_width=True, disabled=(len(current_names) < 2 or len(current_names) > 20 or len(set(current_names)) != len(current_names))):
        project["step"] = 2
        persist_current(False)
        st.rerun()

elif project.get("step") == 2:
    st.subheader("Step 2 · Build the cross-impact matrix")
    st.info("Rows are the affected/target variables (i). Columns are the influencing/source variables (j). Enter coefficients from your course method, typically between −1 and +1.")
    A = matrix_from_project(project)
    uploaded_matrix = st.file_uploader("Optional: import a square matrix CSV", type=["csv"], key="matrix_upload")
    if uploaded_matrix is not None:
        try:
            imported = pd.read_csv(uploaded_matrix, index_col=0)
            imported.index = imported.index.astype(str)
            imported.columns = imported.columns.astype(str)
            if imported.shape[0] != imported.shape[1] or list(imported.index) != list(imported.columns):
                st.error("CSV must contain a square matrix with matching row and column labels.")
            else:
                A = imported.apply(pd.to_numeric, errors="raise")
                project["variables"] = list(A.index)
                project["initial"] = (project["initial"] + [0.5] * len(A))[:len(A)]
                project["matrix"] = A.to_dict(orient="split")
        except Exception as exc:
            st.error(f"Could not import matrix: {exc}")
    A = st.data_editor(A, use_container_width=True, key="matrix_editor")
    try:
        A = A.apply(pd.to_numeric, errors="raise")
        if A.shape[0] != A.shape[1] or list(A.index) != list(A.columns):
            st.error("Matrix must be square with identical row and column labels.")
        elif A.isna().any().any() or not np.isfinite(A.to_numpy()).all():
            st.error("Fill every matrix cell with a finite number.")
        else:
            project["matrix"] = A.to_dict(orient="split")
            metrics, _ = cross_impact_metrics(A)
            st.plotly_chart(px.imshow(A, text_auto=".2f", aspect="auto", title="Cross-impact heatmap"), use_container_width=True)
            st.dataframe(metrics, use_container_width=True, hide_index=True)
    except Exception as exc:
        st.error(f"Matrix validation: {exc}")
    prev, nxt = st.columns(2)
    if prev.button("← Back to variables", use_container_width=True):
        project["step"] = 1
        persist_current(False)
        st.rerun()
    if nxt.button("Continue to settings →", type="primary", use_container_width=True):
        project["step"] = 3
        persist_current(False)
        st.rerun()

elif project.get("step") == 3:
    st.subheader("Step 3 · Simulation settings")
    st.markdown("**Course update rule**")
    st.latex(r"x_i(t+\Delta t)=x_i(t)^{p_i(t)}")
    st.latex(r"p_i(t)=\frac{1+\frac{\Delta t}{2}\sum_j(|a_{ij}|-a_{ij})x_j}{1+\frac{\Delta t}{2}\sum_j(|a_{ij}|+a_{ij})x_j}")
    st.caption("The formula is implemented as shown in your teaching screenshot and workbook. Time increment Δt defaults to 1, matching the workbook.")
    
        c1, c2 = st.columns(2)
        with c1:
            project["steps"] = st.number_input(
                "Number of time steps",
                min_value=1,
                max_value=200,
                value=int(project.get("steps", 10)),
                step=1,
                key="steps_input",
            )
        with c2:
            project["dt"] = st.number_input(
                "Time increment (Δt)",
                min_value=0.1,
                max_value=10.0,
                value=float(project.get("dt", 1.0)),
                step=0.1,
                key="dt_input",
            )

    st.markdown("#### Review before running")
    st.dataframe(pd.DataFrame({"Variable": project["variables"], "Initial state": project["initial"]}), use_container_width=True, hide_index=True)
    st.dataframe(matrix_from_project(project), use_container_width=True)
    prev, nxt = st.columns(2)
    if prev.button("← Back to matrix", use_container_width=True):
        project["step"] = 2
        persist_current(False)
        st.rerun()
    if nxt.button("Continue to results →", type="primary", use_container_width=True):
        project["step"] = 4
        persist_current(False)
        st.rerun()

elif project.get("step") == 4:
    st.subheader("Step 4 · Run and interpret")
    A = matrix_from_project(project)
    c1, c2, c3 = st.columns(3)
with c1:
    st.markdown(
        f'<div style="background:#1e293b;padding:18px;border-radius:10px;'
        f'border:1px solid #475569;color:#ffffff;">'
        f'<div style="font-size:14px;color:#cbd5e1;">Variables</div>'
        f'<div style="font-size:30px;font-weight:bold;color:#ffffff;">'
        f'{len(project["variables"])}</div></div>',
        unsafe_allow_html=True,
    )

with c2:
    st.markdown(
        f'<div style="background:#1e293b;padding:18px;border-radius:10px;'
        f'border:1px solid #475569;color:#ffffff;">'
        f'<div style="font-size:14px;color:#cbd5e1;">Time steps</div>'
        f'<div style="font-size:30px;font-weight:bold;color:#ffffff;">'
        f'{project["steps"]}</div></div>',
        unsafe_allow_html=True,
    )

with c3:
    st.markdown(
        f'<div style="background:#1e293b;padding:18px;border-radius:10px;'
        f'border:1px solid #475569;color:#ffffff;">'
        f'<div style="font-size:14px;color:#cbd5e1;">Δt</div>'
        f'<div style="font-size:30px;font-weight:bold;color:#ffffff;">'
        f'{project["dt"]}</div></div>',
        unsafe_allow_html=True,
    )
    if st.button("▶ Run KSIM", type="primary", use_container_width=True):
        try:
            history, exponents = run_ksim(project["initial"], A.to_numpy(float), int(project["steps"]), float(project["dt"]))
            result_df = pd.DataFrame(history, columns=project["variables"])
            result_df.insert(0, "Time", np.arange(len(result_df)) * float(project["dt"]))
            exponent_df = pd.DataFrame(exponents, columns=project["variables"])
            exponent_df.insert(0, "Time", np.arange(1, len(exponent_df) + 1) * float(project["dt"]))
            project["results"] = result_df.to_dict(orient="split")
            project["exponents"] = exponent_df.to_dict(orient="split")
            project["last_run_at"] = datetime.now().isoformat(timespec="seconds")
            persist_current(False)
            st.success("Simulation complete and results saved to this project.")
        except Exception as exc:
            st.error(f"Simulation failed: {exc}")
    if project.get("results"):
        results = pd.DataFrame(project["results"]["data"], columns=project["results"]["columns"])
        st.subheader("System behaviour over time")
        st.plotly_chart(px.line(results, x="Time", y=project["variables"], markers=True), use_container_width=True)
        st.subheader("Initial vs final state")
        summary = pd.DataFrame({
            "Variable": project["variables"],
            "Initial": [float(results.iloc[0][v]) for v in project["variables"]],
            "Final": [float(results.iloc[-1][v]) for v in project["variables"]],
        })
        summary["Change"] = summary["Final"] - summary["Initial"]
        summary["Direction"] = np.where(summary["Change"] > 1e-9, "Increased", np.where(summary["Change"] < -1e-9, "Decreased", "Unchanged"))
        st.dataframe(summary, use_container_width=True, hide_index=True)
        st.download_button("Download results CSV", results.to_csv(index=False).encode("utf-8"), file_name="ksim_results.csv", mime="text/csv")
        if project.get("exponents"):
            with st.expander("Inspect calculated KSIM exponents"):
                exps = pd.DataFrame(project["exponents"]["data"], columns=project["exponents"]["columns"])
                st.dataframe(exps, use_container_width=True)
        st.markdown("#### Save a scenario")
        scenario_name = st.text_input("Scenario name", value="Scenario 1", key="scenario_name")
        if st.button("Save current run as scenario"):
            project.setdefault("scenarios", []).append({
                "name": scenario_name, "results": project["results"],
                "initial": project["initial"], "matrix": project["matrix"],
                "steps": project["steps"], "dt": project["dt"],
            })
            persist_current(False)
            st.success("Scenario saved to project.")
        if project.get("scenarios"):
            st.markdown("#### Saved scenarios")
            for idx, scenario in enumerate(project["scenarios"]):
                st.write(f"**{scenario['name']}** — {scenario['steps']} steps, Δt={scenario['dt']}")
            if len(project["scenarios"]) >= 2:
                choices = [s["name"] for s in project["scenarios"]]
                selected = st.multiselect("Choose scenarios to compare", choices, default=choices[:2])
                if len(selected) >= 2:
                    fig = None
                    for scenario in project["scenarios"]:
                        if scenario["name"] in selected:
                            sdf = pd.DataFrame(scenario["results"]["data"], columns=scenario["results"]["columns"])
                            melted = sdf.melt(id_vars=["Time"], var_name="Variable", value_name="State")
                            melted["Scenario"] = scenario["name"]
                            fig = pd.concat([fig, melted], ignore_index=True) if fig is not None else melted
                    st.plotly_chart(px.line(fig, x="Time", y="State", color="Scenario", facet_col="Variable", facet_col_wrap=2), use_container_width=True)
        with st.expander("Method and assumptions"):
            st.code(KSIM_METHOD)
            st.write("States are expected to be normalized to [0,1]. Positive coefficients increase the denominator term; negative coefficients increase the numerator term, as defined by the course equation.")
    prev, save = st.columns(2)
    if prev.button("← Back to settings", use_container_width=True):
        project["step"] = 3
        persist_current(False)
        st.rerun()
    if save.button("Save project", type="primary", use_container_width=True):
        persist_current()

# Export/import full project JSON so students can back up or move their work.
with st.sidebar:
    st.divider()
    st.markdown("### Project backup")
    if st.session_state.project:
        p = st.session_state.project
        st.download_button("Export project JSON", data=json.dumps(p, indent=2), file_name=f"{p['name'].replace(' ','_')}.json", mime="application/json", use_container_width=True)
    import_json = st.file_uploader("Restore project JSON", type=["json"], key="restore_project")
    if import_json is not None and st.button("Restore uploaded project", use_container_width=True):
        try:
            restored = json.load(import_json)
            if not all(k in restored for k in ["id", "name", "variables", "initial", "matrix"]):
                raise ValueError("This file does not look like a Systems Thinking Studio project.")
            restored["id"] = str(uuid.uuid4())
            st.session_state.project = restored
            save_project(restored)
            go("builder")
            st.rerun()
        except Exception as exc:
            st.error(f"Could not restore project: {exc}")
