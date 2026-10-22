from __future__ import annotations
import json, sqlite3, uuid
from datetime import datetime
from pathlib import Path
import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st
from analysis_core import KSIM_METHOD, cross_impact_metrics, matrix_from_project, new_project, run_ksim, validate_project

APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "systems_thinking_projects.db"
st.set_page_config(page_title="Systems Thinking Studio", page_icon="🧭", layout="wide")

def db_connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("""CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, name TEXT NOT NULL, updated_at TEXT NOT NULL, payload TEXT NOT NULL)""")
    conn.commit()
    return conn

def save_project(project):
    validate_project(project, require_results=False)
    project["updated_at"] = datetime.now().isoformat(timespec="seconds")
    with db_connect() as conn:
        conn.execute("""INSERT INTO projects (id,name,updated_at,payload) VALUES (?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET name=excluded.name, updated_at=excluded.updated_at, payload=excluded.payload""",
        (project["id"], project["name"], project["updated_at"], json.dumps(project, ensure_ascii=False)))

def list_projects():
    with db_connect() as conn:
        return conn.execute("SELECT id,name,updated_at FROM projects ORDER BY updated_at DESC").fetchall()

def load_project(pid):
    with db_connect() as conn:
        row = conn.execute("SELECT payload FROM projects WHERE id=?", (pid,)).fetchone()
    if row is None: raise KeyError("Saved project not found.")
    project = json.loads(row[0]); validate_project(project); return project

def delete_project(pid):
    with db_connect() as conn: conn.execute("DELETE FROM projects WHERE id=?", (pid,))

def persist_current(show_message=True):
    p = st.session_state.get("project")
    if p:
        save_project(p)
        if show_message: st.toast("Project saved.", icon="✅")

def set_project(project, page="builder"):
    st.session_state["project"] = project
    st.session_state["page"] = page

def render_sidebar():
    with st.sidebar:
        st.markdown("## 🧭 Systems Thinking Studio")
        st.caption("Build a model one step at a time.")
        p = st.session_state.get("project")
        if p:
            st.info(f"Current project\n\n**{p['name']}**")
            if st.button("💾 Save project", type="primary", use_container_width=True):
                try: persist_current()
                except Exception as e: st.error(f"Could not save project: {e}")
            if st.button("Project dashboard", use_container_width=True):
                st.session_state["page"] = "home"; st.rerun()
            st.divider(); st.markdown("### Project backup")
            st.download_button("Export project JSON", json.dumps(p, indent=2, ensure_ascii=False),
                file_name=f"{p['name'].strip().replace(' ','_')}.json", mime="application/json", use_container_width=True)
            uploaded = st.file_uploader("Restore project JSON", type=["json"], key="restore_project_file")
            if st.button("Restore uploaded project", disabled=uploaded is None, use_container_width=True):
                try:
                    restored = json.load(uploaded); validate_project(restored)
                    restored["id"] = str(uuid.uuid4()); restored["name"] = restored.get("name", "Restored project") + " (restored)"
                    set_project(restored); save_project(restored)
                    st.success("Project restored and saved separately."); st.rerun()
                except Exception as e: st.error(f"Could not restore project: {e}")
        st.divider()
        st.caption("KSIM convention: rows are targets; columns are sources.")
        st.caption("Initial states are normalized between 0 and 1.")
        st.caption("Keep JSON backups; hosted local storage may not survive restarts or redeployments.")

def render_home():
    st.markdown("""<div style="background:linear-gradient(110deg,#15314a,#17616c);padding:24px 28px;border-radius:16px;color:white;margin-bottom:22px"><h1 style="margin:0">Systems Thinking Studio</h1><p style="margin:8px 0 0">Build, simulate, save and compare systems-thinking models.</p></div>""", unsafe_allow_html=True)
    st.subheader("Your projects")
    left, right = st.columns(2)
    with left:
        with st.form("new_project_form", clear_on_submit=True):
            name = st.text_input("New project name", value="My KSIM model")
            create = st.form_submit_button("＋ Create project", type="primary", use_container_width=True)
        if create:
            p = new_project(name.strip() or "Untitled KSIM project")
            try: save_project(p); set_project(p); st.rerun()
            except Exception as e: st.error(f"Could not create project: {e}")
    with right:
        st.markdown("#### Start with a course example")
        if st.button("Load Parthenium teaching example", use_container_width=True):
            p = new_project("Parthenium – AS-IS")
            try: save_project(p); set_project(p); st.rerun()
            except Exception as e: st.error(f"Could not load example: {e}")
    st.divider()
    saved = list_projects()
    if not saved: st.info("No saved projects yet. Create one above; it will appear here."); return
    for pid, name, updated in saved:
        a,b,c = st.columns([3,2,1])
        a.markdown(f"**{name}**"); a.caption(f"Last saved: {updated.replace('T',' ')}")
        if b.button("Open", key=f"open_{pid}", use_container_width=True):
            try: set_project(load_project(pid)); st.rerun()
            except Exception as e: st.error(f"Could not open project: {e}")
        if c.button("Delete", key=f"delete_{pid}", use_container_width=True):
            delete_project(pid)
            if st.session_state.get("project",{}).get("id")==pid: st.session_state["project"]=None; st.session_state["page"]="home"
            st.rerun()
    st.caption("This version stores projects in a local SQLite file. On Streamlit Cloud, persistence across restarts/redeployments is not guaranteed; export JSON backups.")

def render_builder(p):
    st.title(p["name"])
    labels=["Variables","Cross-impact matrix","Simulation settings","Run & results"]
    step=int(p.get("step",1)); st.progress(step/4, text=f"Step {step} of 4 · {labels[step-1]}")
    cols=st.columns(4)
    for i,label in enumerate(labels,1): cols[i-1].markdown(("➡️ **" if i==step else "")+f"{i}. {label}"+("**" if i==step else ""))
    if step==1:
        st.subheader("Step 1 · Define variables")
        st.write("Each variable represents an attribute. Initial states must be between 0 and 1.")
        names_text=st.text_area("Variable names — one per line", value="\n".join(p["variables"]), height=160, key=f"names_{p['id']}")
        names=[x.strip() for x in names_text.splitlines() if x.strip()]
        valid=len(names)>=2 and len(names)<=20 and len(set(names))==len(names)
        if not valid: st.error("Use 2–20 unique variable names.")
        elif names!=p["variables"]:
            old=matrix_from_project(p); old_init=dict(zip(p["variables"],p["initial"]))
            new=pd.DataFrame(0.0,index=names,columns=names)
            for r in names:
                for c in names:
                    if r in old.index and c in old.columns: new.loc[r,c]=float(old.loc[r,c])
            p["variables"]=names; p["initial"]=[float(old_init.get(n,.5)) for n in names]
            p["matrix"]=new.to_dict(orient="split"); p["results"]=None; p["exponents"]=None
        init_df=pd.DataFrame({"Variable":p["variables"],"Initial state (0–1)":p["initial"]})
        edited=st.data_editor(init_df,use_container_width=True,hide_index=True,disabled=["Variable"],key=f"initial_{p['id']}")
        try:
            vals=pd.to_numeric(edited["Initial state (0–1)"],errors="raise").astype(float).tolist()
            if any(not np.isfinite(v) or v<0 or v>1 for v in vals): raise ValueError("Each value must be between 0 and 1.")
            p["initial"]=vals
        except Exception as e: st.error(f"Invalid initial state: {e}"); valid=False
        if st.button("Continue to matrix →",type="primary",use_container_width=True,disabled=not valid):
            p["step"]=2; persist_current(False); st.rerun()
    elif step==2:
        st.subheader("Step 2 · Build the cross-impact matrix")
        st.info("Rows are affected/target variables (i); columns are influencing/source variables (j).")
        A=matrix_from_project(p)
        upload=st.file_uploader("Optional: import square matrix CSV",type=["csv"],key=f"matrix_upload_{p['id']}")
        if upload is not None:
            try:
                imported=pd.read_csv(upload,index_col=0); imported.index=imported.index.astype(str); imported.columns=imported.columns.astype(str)
                imported=imported.apply(pd.to_numeric,errors="raise")
                if imported.shape[0]!=imported.shape[1] or list(imported.index)!=list(imported.columns): raise ValueError("CSV must be square with matching row and column labels.")
                if list(imported.index)!=p["variables"]: raise ValueError("CSV labels/order must match current variables.")
                if not np.isfinite(imported.to_numpy(float)).all(): raise ValueError("Matrix must contain finite numbers.")
                A=imported; p["matrix"]=A.to_dict(orient="split")
            except Exception as e: st.error(f"Could not import matrix: {e}")
        edited=st.data_editor(A,use_container_width=True,key=f"matrix_{p['id']}")
        try:
            edited=edited.apply(pd.to_numeric,errors="raise")
            if edited.shape[0]!=edited.shape[1] or list(edited.index)!=list(edited.columns): raise ValueError("Matrix must be square with matching labels.")
            if not np.isfinite(edited.to_numpy(float)).all(): raise ValueError("Every cell must be a finite number.")
            p["matrix"]=edited.to_dict(orient="split")
            st.plotly_chart(px.imshow(edited,text_auto=".2f",aspect="auto",title="Cross-impact heatmap"),use_container_width=True)
            st.dataframe(cross_impact_metrics(edited),use_container_width=True,hide_index=True)
            matrix_ok=True
        except Exception as e: st.error(f"Matrix validation: {e}"); matrix_ok=False
        a,b=st.columns(2)
        if a.button("← Back to variables",use_container_width=True): p["step"]=1; persist_current(False); st.rerun()
        if b.button("Continue to settings →",type="primary",use_container_width=True,disabled=not matrix_ok): p["step"]=3; persist_current(False); st.rerun()
    elif step==3:
        st.subheader("Step 3 · Simulation settings")
        st.markdown("**Course update rule**")
        st.latex(r"x_i(t+\Delta t)=x_i(t)^{p_i(t)}")
        st.latex(r"p_i(t)=\frac{1+\frac{\Delta t}{2}\sum_j(|a_{ij}|-a_{ij})x_j}{1+\frac{\Delta t}{2}\sum_j(|a_{ij}|+a_{ij})x_j}")
        st.caption("Uses the KSIM equation from the course material. Δt defaults to 1.")
        c1,c2=st.columns(2)
        with c1:
            p["steps"]=st.number_input("Number of time steps",min_value=1,max_value=200,value=int(p.get("steps",15)),step=1,key=f"steps_{p['id']}")
        with c2:
            p["dt"]=st.number_input("Time increment (Δt)",min_value=.1,max_value=10.0,value=float(p.get("dt",1.0)),step=.1,key=f"dt_{p['id']}")
        st.markdown("#### Review before running")
        st.dataframe(pd.DataFrame({"Variable":p["variables"],"Initial state":p["initial"]}),use_container_width=True,hide_index=True)
        st.dataframe(matrix_from_project(p),use_container_width=True)
        a,b=st.columns(2)
        if a.button("← Back to matrix",use_container_width=True): p["step"]=2; persist_current(False); st.rerun()
        if b.button("Continue to results →",type="primary",use_container_width=True): p["step"]=4; persist_current(False); st.rerun()
    elif step==4:
        st.subheader("Step 4 · Run and interpret")
        A=matrix_from_project(p); c1,c2,c3=st.columns(3)
        c1.metric("Variables",len(p["variables"])); c2.metric("Time steps",int(p["steps"])); c3.metric("Δt",float(p["dt"]))
        if st.button("▶ Run KSIM",type="primary",use_container_width=True):
            try:
                history,exponents=run_ksim(p["initial"],A.to_numpy(float),int(p["steps"]),float(p["dt"]))
                result=pd.DataFrame(history,columns=p["variables"]); result.insert(0,"Time",np.arange(len(result))*float(p["dt"]))
                exp_df=pd.DataFrame(exponents,columns=p["variables"]); exp_df.insert(0,"Time",np.arange(1,len(exp_df)+1)*float(p["dt"]))
                p["results"]=result.to_dict(orient="split"); p["exponents"]=exp_df.to_dict(orient="split")
                p["last_run_at"]=datetime.now().isoformat(timespec="seconds"); persist_current(False); st.success("Simulation complete and saved.")
            except Exception as e: st.error(f"Simulation failed: {e}")
        if p.get("results"):
            result=pd.DataFrame(p["results"]["data"],columns=p["results"]["columns"],index=p["results"].get("index"))
            st.subheader("System behaviour over time")
            long=result.melt(id_vars="Time",var_name="Variable",value_name="State")
            fig=px.line(long,x="Time",y="State",color="Variable",markers=True); fig.update_yaxes(range=[0,1])
            st.plotly_chart(fig,use_container_width=True)
            initial=result.iloc[0]; final=result.iloc[-1]
            summary=pd.DataFrame({"Variable":p["variables"],"Initial":[float(initial[n]) for n in p["variables"]],"Final":[float(final[n]) for n in p["variables"]]})
            summary["Change"]=summary["Final"]-summary["Initial"]
            summary["Direction"]=summary["Change"].map(lambda x:"Increased" if x>1e-9 else ("Decreased" if x< -1e-9 else "Unchanged"))
            st.subheader("Initial vs final state"); st.dataframe(summary.round(6),use_container_width=True,hide_index=True)
            st.download_button("Download results CSV",result.to_csv(index=False),file_name=f"{p['name'].replace(' ','_')}_results.csv",mime="text/csv")
            with st.expander("Inspect calculated KSIM exponents"):
                exp=pd.DataFrame(p["exponents"]["data"],columns=p["exponents"]["columns"],index=p["exponents"].get("index"))
                st.dataframe(exp,use_container_width=True,hide_index=True)
        with st.expander("Method and assumptions"): st.write(KSIM_METHOD); st.write("States are clipped to [0,1] after each update. Results depend on the matrix, initial states, number of steps and Δt.")
        a,b=st.columns(2)
        if a.button("← Back to settings",use_container_width=True): p["step"]=3; persist_current(False); st.rerun()
        if b.button("Save project",type="primary",use_container_width=True):
            try: persist_current()
            except Exception as e: st.error(f"Could not save project: {e}")

def main():
    if "page" not in st.session_state: st.session_state["page"]="home"
    if "project" not in st.session_state: st.session_state["project"]=None
    render_sidebar()
    if st.session_state["page"]=="home" or not st.session_state.get("project"): render_home()
    else: render_builder(st.session_state["project"])
if __name__=="__main__": main()
