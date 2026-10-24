from __future__ import annotations
import json, os, io
from datetime import datetime
import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from analysis_core import run_ksim, denormalize_ksim, cross_impact_metrics

st.set_page_config(page_title="Systems Thinking Portal", page_icon="🧭", layout="wide")
st.markdown("""<style>.block-container{padding-top:1.3rem;max-width:1500px}.hero{padding:1.25rem 1.5rem;border-radius:14px;background:linear-gradient(120deg,#12263a,#245b78);color:white;margin-bottom:1rem}.hero h1{color:white;margin:0}.hero p{color:#e4edf4;margin:.4rem 0 0}</style><div class="hero"><h1>Systems Thinking Analysis Portal</h1><p>Model the AS-IS system, test multiple TO-BE interventions, and compare outcomes.</p></div>""", unsafe_allow_html=True)

# ---------------- Auth and cloud persistence ----------------
def get_supabase():
    try:
        from supabase import create_client
        url = st.secrets.get("SUPABASE_URL", os.getenv("SUPABASE_URL", ""))
        key = st.secrets.get("SUPABASE_ANON_KEY", os.getenv("SUPABASE_ANON_KEY", ""))
        if not url or not key:
            return None, "Supabase credentials are not configured."
        return create_client(url, key), None
    except Exception as exc:
        return None, f"Supabase setup error: {exc}"

sb, sb_error = get_supabase()
if "auth_session" not in st.session_state: st.session_state.auth_session = None
if "user" not in st.session_state: st.session_state.user = None
if "active_workspace" not in st.session_state: st.session_state.active_workspace = "personal"

if sb is None:
    st.error("Login/database setup is required before the portal can be used.")
    st.write(sb_error)
    st.markdown("Open `README.txt` in the ZIP and complete the Supabase setup, then add `SUPABASE_URL` and `SUPABASE_ANON_KEY` to Streamlit Secrets.")
    st.stop()

# Streamlit reruns create a new Supabase client. Restore the authenticated
# session on EVERY rerun before any table queries are made. Checking only
# `not st.session_state.user` is insufficient because `user` remains populated
# after login while `sb` is a newly created, unauthenticated client.
if st.session_state.auth_session:
    try:
        saved_session = st.session_state.auth_session
        sb.auth.set_session(
            saved_session.access_token,
            saved_session.refresh_token,
        )
        # Keep the latest session in case Supabase refreshed its tokens.
        current_session = sb.auth.get_session()
        if current_session is not None:
            st.session_state.auth_session = current_session
        st.session_state.user = sb.auth.get_user().user
    except Exception as exc:
        st.session_state.user = None
        st.session_state.auth_session = None
        st.warning(
            "Your login session could not be restored. Please log in again. "
            f"Details: {exc}"
        )

if not st.session_state.user:
    st.subheader("Sign in or create a student account")
    st.caption("Open registration is enabled. Use an email address you can access to verify your account if email confirmation is enabled in Supabase.")
    tab_login, tab_register = st.tabs(["Log in", "Create account"])
    with tab_login:
        with st.form("login_form"):
            email = st.text_input("Email", key="login_email")
            password = st.text_input("Password", type="password", key="login_password")
            submit_login = st.form_submit_button("Log in", type="primary", use_container_width=True)
        if submit_login:
            try:
                response = sb.auth.sign_in_with_password({"email": email.strip(), "password": password})
                st.session_state.user = response.user
                st.session_state.auth_session = response.session
                st.rerun()
            except Exception as exc: st.error(f"Login failed: {exc}")
    with tab_register:
        with st.form("register_form"):
            name = st.text_input("Full name")
            reg_email = st.text_input("Email address")
            reg_password = st.text_input("Create password", type="password")
            confirm_password = st.text_input("Confirm password", type="password")
            submit_register = st.form_submit_button("Create account", type="primary", use_container_width=True)
        if submit_register:
            if not name.strip() or not reg_email.strip(): st.error("Enter your name and email.")
            elif len(reg_password) < 8: st.error("Use a password with at least 8 characters.")
            elif reg_password != confirm_password: st.error("Passwords do not match.")
            else:
                try:
                    response = sb.auth.sign_up({"email": reg_email.strip(), "password": reg_password, "options": {"data": {"full_name": name.strip()}}})
                    if getattr(response, "session", None):
                        st.session_state.user = response.user
                        st.session_state.auth_session = response.session
                        st.success("Account created.")
                        st.rerun()
                    else:
                        st.success("Account created. Check your email if confirmation is required, then log in.")
                except Exception as exc: st.error(f"Registration failed: {exc}")
    st.stop()

user = st.session_state.user
uid = str(user.id)
with st.sidebar:
    st.markdown("### Account")
    st.write(getattr(user, "email", "Signed in"))
    if st.button("Log out", use_container_width=True):
        try: sb.auth.sign_out()
        except Exception: pass
        st.session_state.user = None; st.session_state.auth_session = None
        st.rerun()
    st.divider()
    st.markdown("### Workspaces")
    workspace_mode = st.radio("Workspace", ["My projects", "Group workspace"], key="workspace_mode")

# Group management relies on RLS policies in schema.sql. Users only see groups they belong to.
def fetch_groups():
    try:
        memberships = sb.table("group_members").select("group_id, role, groups(id,name,created_by)").eq("user_id", uid).execute().data or []
        out=[]
        for row in memberships:
            g=row.get("groups")
            if isinstance(g, dict): out.append({"id":g.get("id"),"name":g.get("name"),"role":row.get("role","member")})
        return out
    except Exception as exc:
        st.warning(f"Could not load groups: {exc}")
        return []

groups = fetch_groups()
workspace_id = None
workspace_label = "Personal workspace"
if workspace_mode == "Group workspace":
    with st.sidebar:
        if groups:
            options = {f"{g['name']} ({g['role']})":g for g in groups}
            selected_group_label = st.selectbox("Choose group", list(options))
            selected_group = options[selected_group_label]
            workspace_id = selected_group["id"]
            workspace_label = selected_group["name"]
        else:
            st.caption("You are not a member of a group yet. Create one below or ask a group owner to add you.")
        with st.expander("Create a group"):
            group_name = st.text_input("Group name", key="new_group_name")
            if st.button("Create group", key="create_group"):
                if not group_name.strip(): st.error("Enter a group name.")
                else:
                    try:
                        created=sb.table("groups").insert({"name":group_name.strip(),"created_by":uid}).execute().data
                        gid=created[0]["id"]
                        sb.table("group_members").insert({"group_id":gid,"user_id":uid,"role":"owner"}).execute()
                        st.success(f"Group created. Share this join code with your teammates: {created[0].get('join_code', 'See Supabase groups table')}")
                        st.rerun()
                    except Exception as exc: st.error(f"Could not create group: {exc}")
        with st.expander("Join an existing group"):
            join_code = st.text_input("Group join code", key="join_group_code")
            if st.button("Join group", key="join_group_button"):
                if not join_code.strip(): st.error("Enter the join code shared by your group owner.")
                else:
                    try:
                        sb.rpc("join_group_by_code", {"code": join_code.strip()}).execute()
                        st.success("Joined group successfully.")
                        st.rerun()
                    except Exception as exc: st.error(f"Could not join group: {exc}")

# project save/load; database RLS prevents cross-user / cross-group access.
def load_projects():
    try:
        q=sb.table("projects").select("id,name,workspace_type,group_id,updated_at,payload")
        if workspace_id:
            q=q.eq("workspace_type","group").eq("group_id",workspace_id)
        else:
            q=q.eq("workspace_type","personal").eq("owner_id",uid)
        return q.order("updated_at", desc=True).execute().data or []
    except Exception as exc:
        st.warning(f"Could not load projects. Check schema.sql and Supabase RLS setup. Details: {exc}")
        return []

projects=load_projects()
project_options={f"{p['name']} · updated {str(p.get('updated_at',''))[:10]}":p for p in projects}
with st.sidebar:
    st.divider()
    st.markdown("### Saved projects")
    selected_project_label=st.selectbox("Open a saved project", ["— New project —"]+list(project_options), key="project_picker")
    project_to_load=project_options.get(selected_project_label)
    if project_to_load and st.button("Load selected project", use_container_width=True):
        st.session_state.project_payload=project_to_load.get("payload") or {}
        st.session_state.project_id=project_to_load.get("id")
        st.session_state.project_name=project_to_load.get("name", "Untitled project")
        st.rerun()
    if selected_project_label == "— New project —" and "project_payload" not in st.session_state:
        st.session_state.project_payload={}
        st.session_state.project_id=None
        st.session_state.project_name="Untitled project"

payload=st.session_state.get("project_payload", {})
project_name=st.text_input("Project name", value=st.session_state.get("project_name","Untitled project"), key="project_name_input")
st.session_state.project_name=project_name
st.caption(f"Workspace: {workspace_label} · AS-IS and TO-BE models are saved within this workspace.")

# ---------------- Project configuration ----------------
st.header("1. Define your problem and variables")
problem = st.text_area("Problem statement", value=payload.get("problem", ""), placeholder="Describe the system or problem you want to study.")
entity_text = st.text_area("Entities and their descriptions (one per line: Entity — description)", value=payload.get("entities_text", ""), placeholder="City residents — people affected by the issue\nGovernment — policy and enforcement actor\nParthenium — invasive weed")
variables_text = st.text_area("Modelled variables / attributes (one per line)", value=payload.get("variables_text", ""), placeholder="Parthenium abundance\nPollen exposure\nAsthma incidence\nPublic awareness")
var_names=[v.strip() for v in variables_text.splitlines() if v.strip()]
if len(var_names)<2: st.info("Add at least two variables to configure the matrices and simulations.")
if len(var_names)>20: st.error("For this interactive version, use at most 20 variables.")

# Helpers for square matrices
def matrix_editor(label, defaults, key):
    st.subheader(label)
    return st.data_editor(defaults, use_container_width=True, key=key, num_rows="fixed")

def fresh_matrix(names, existing=None):
    if existing:
        df=pd.DataFrame(existing)
        if list(df.index.astype(str)) == names and list(df.columns.astype(str)) == names: return df
    return pd.DataFrame(np.zeros((len(names),len(names))), index=names, columns=names, dtype=float)

if 2 <= len(var_names) <= 20:
    st.caption("Matrix convention for KSIM: rows are target variables and columns are source variables. Positive values represent reinforcing influence; negative values represent inhibiting influence. Use values between -1 and +1.")
    default_as_is=fresh_matrix(var_names, payload.get("asis_matrix"))
    asis=matrix_editor("2. AS-IS cross-impact matrix", default_as_is, "asis_matrix_editor")
    try:
        asis=asis.apply(pd.to_numeric, errors="raise")
        if asis.isna().any().any() or not np.isfinite(asis.to_numpy()).all(): raise ValueError("Fill every matrix cell with a finite number.")
        if (asis.abs().to_numpy()>1).any(): raise ValueError("Each impact value must be between -1 and +1.")
    except Exception as exc:
        st.error(f"AS-IS matrix needs attention: {exc}")
        st.stop()

    st.subheader("3. Initial values and simulation settings")
    default_settings=payload.get("settings")
    if default_settings and [x.get("Variable") for x in default_settings] == var_names:
        settings_df=pd.DataFrame(default_settings)
    else:
        settings_df=pd.DataFrame({"Variable":var_names,"Initial value":[0.5]*len(var_names),"Minimum":[0.0]*len(var_names),"Maximum":[1.0]*len(var_names)})
    settings=st.data_editor(settings_df,use_container_width=True,hide_index=True,num_rows="fixed",key="settings_editor",disabled=["Variable"])
    c1,c2=st.columns(2)
    steps=int(c1.number_input("Simulation periods after T0",min_value=1,max_value=100,value=int(payload.get("steps",10)),step=1))
    dt=float(c2.number_input("Time-step multiplier",min_value=0.1,max_value=5.0,value=float(payload.get("dt",1.0)),step=0.1))

    st.header("4. TO-BE: Select and define interventions")
    st.write("You can add new intervention variables or represent an intervention through changed relationships among existing variables. The portal will not invent causal impacts; you define their strengths below.")
    default_interventions=payload.get("interventions", [{"Select":False,"Intervention":"Biological control beetle","Type":"New variable","Variable name":"Beetle abundance","Description":"Beetle reduces Parthenium abundance"}])
    intervention_df=pd.DataFrame(default_interventions)
    for col, default in [("Select",False),("Intervention","Intervention"),("Type","New variable"),("Variable name",""),("Description","")]:
        if col not in intervention_df: intervention_df[col]=default
    intervention_df=intervention_df[["Select","Intervention","Type","Variable name","Description"]]
    interventions=st.data_editor(intervention_df,use_container_width=True,num_rows="dynamic",key="interventions_editor",column_config={"Select":st.column_config.CheckboxColumn("Apply simultaneously?"),"Type":st.column_config.SelectboxColumn("Intervention type",options=["New variable","Modify existing relationships"])} )
    chosen=interventions[interventions["Select"].fillna(False).astype(bool)].copy()
    st.caption(f"Selected interventions: {len(chosen)}. Select multiple rows to apply several interventions at once.")

    # Build target variable list from baseline variables plus selected new-variable interventions.
    tobe_names=list(var_names)
    new_intervention_vars=[]
    for _,row in chosen.iterrows():
        if str(row.get("Type",""))=="New variable":
            nm=str(row.get("Variable name","")).strip()
            if nm and nm not in tobe_names:
                tobe_names.append(nm); new_intervention_vars.append(nm)
    if len(tobe_names)>20:
        st.error("Selected interventions would create more than 20 variables. Reduce the number of variables or interventions.")
        st.stop()
    st.subheader("5. TO-BE cross-impact matrix")
    auto_key="auto_matrix_"+"_".join(tobe_names)
    # Start from AS-IS relationships; newly introduced variables receive zero relationships until specified.
    tobe_default=fresh_matrix(tobe_names)
    tobe_default.loc[var_names,var_names]=asis.to_numpy()
    saved_tobe=payload.get("tobe_matrix")
    if saved_tobe:
        saved_df=pd.DataFrame(saved_tobe)
        common_rows=[x for x in tobe_names if x in saved_df.index]
        common_cols=[x for x in tobe_names if x in saved_df.columns]
        if common_rows and common_cols: tobe_default.loc[common_rows,common_cols]=saved_df.loc[common_rows,common_cols]
    # Explicit intervention relationship rules provide deterministic auto-generation.
    st.markdown("**Automatic matrix generation rules**")
    st.caption("For each selected intervention, enter a target variable, source variable, and impact strength. These rules are used to generate the TO-BE matrix. You can then manually edit any cell below.")
    rules=[]
    for idx,(_,row) in enumerate(chosen.iterrows()):
        intervention_name=str(row.get("Intervention",f"Intervention {idx+1}"))
        suggested_source=str(row.get("Variable name","")).strip() if str(row.get("Type",""))=="New variable" else (var_names[0] if var_names else "")
        if suggested_source not in tobe_names: suggested_source=tobe_names[0]
        st.markdown(f"**{intervention_name}**")
        rc1,rc2,rc3=st.columns([2,2,1])
        target=rc1.selectbox("Target variable",tobe_names,index=0,key=f"rule_target_{idx}")
        source=rc2.selectbox("Source variable",tobe_names,index=tobe_names.index(suggested_source),key=f"rule_source_{idx}")
        impact=float(rc3.number_input("Impact (-1 to +1)",min_value=-1.0,max_value=1.0,value=-0.5 if "reduce" in str(row.get("Description","")).lower() else -0.3,step=0.1,key=f"rule_impact_{idx}"))
        rules.append({"intervention":intervention_name,"target":target,"source":source,"impact":impact})
    if st.button("Generate TO-BE matrix from intervention rules", type="secondary"):
        generated=tobe_default.copy()
        for rule in rules:
            generated.loc[rule["target"],rule["source"]]=rule["impact"]
        st.session_state.generated_tobe_matrix=generated
        st.session_state["tobe_matrix_editor"]=generated
        st.success("Generated a TO-BE matrix from the relationships you specified. Review and edit it below.")
    if "generated_tobe_matrix" in st.session_state and list(st.session_state.generated_tobe_matrix.index)==tobe_names:
        tobe_base=st.session_state.generated_tobe_matrix.copy()
    else: tobe_base=tobe_default.copy()
    tobe=matrix_editor("Editable TO-BE matrix (manual edits are supported)", tobe_base, "tobe_matrix_editor")
    try:
        tobe=tobe.apply(pd.to_numeric,errors="raise")
        if tobe.isna().any().any() or not np.isfinite(tobe.to_numpy()).all(): raise ValueError("Fill every matrix cell with a finite number.")
        if (tobe.abs().to_numpy()>1).any(): raise ValueError("Each impact value must be between -1 and +1.")
    except Exception as exc:
        st.error(f"TO-BE matrix needs attention: {exc}")
        st.stop()

    # Intervention initial values are set separately; all original variables keep AS-IS initial values.
    base_settings=settings.copy()
    try:
        init=pd.to_numeric(base_settings["Initial value"],errors="raise").to_numpy(float)
        mins=pd.to_numeric(base_settings["Minimum"],errors="raise").to_numpy(float)
        maxs=pd.to_numeric(base_settings["Maximum"],errors="raise").to_numpy(float)
        if not np.isfinite(init).all() or not np.isfinite(mins).all() or not np.isfinite(maxs).all(): raise ValueError("Initial values and bounds must be finite.")
        if (maxs<=mins).any() or ((init<mins)|(init>maxs)).any(): raise ValueError("Check that maximum > minimum and each initial value is within its bounds.")
    except Exception as exc:
        st.error(f"Initial values error: {exc}")
        st.stop()
    settings_map={r["Variable"]:r for r in settings.to_dict("records")}
    for nm in new_intervention_vars:
        st.markdown(f"**Initial value for new variable: {nm}**")
        ic1,ic2,ic3=st.columns(3)
        settings_map[nm]={"Variable":nm,"Initial value":float(ic1.number_input(f"{nm} initial value",value=0.2,key=f"init_{nm}")),"Minimum":float(ic2.number_input(f"{nm} minimum",value=0.0,key=f"min_{nm}")),"Maximum":float(ic3.number_input(f"{nm} maximum",value=1.0,key=f"max_{nm}"))}

    if st.button("Run AS-IS and TO-BE simulations",type="primary",use_container_width=True):
        try:
            if not np.isfinite(tobe.to_numpy(float)).all(): raise ValueError("TO-BE matrix contains invalid values.")
            # AS-IS baseline
            asis_initial=(init-mins)/(maxs-mins)
            asis_hist, asis_exp=run_ksim(asis_initial,asis.to_numpy(float),steps=steps,dt=dt)
            asis_actual=denormalize_ksim(asis_hist,mins,maxs)
            asis_result=pd.DataFrame(asis_actual,columns=var_names)
            asis_result.insert(0,"Time",[f"T{i}" for i in range(len(asis_result))])
            # TO-BE initial state: original values plus configured values for new intervention variables.
            tobe_init=[]; tobe_min=[]; tobe_max=[]
            for nm in tobe_names:
                item=settings_map.get(nm,{"Initial value":0.2,"Minimum":0.0,"Maximum":1.0})
                mn=float(item["Minimum"]); mx=float(item["Maximum"]); iv=float(item["Initial value"])
                if mx<=mn or iv<mn or iv>mx: raise ValueError(f"Check initial value and bounds for {nm}.")
                tobe_min.append(mn); tobe_max.append(mx); tobe_init.append((iv-mn)/(mx-mn))
            tobe_hist,tobe_exp=run_ksim(np.asarray(tobe_init),tobe.to_numpy(float),steps=steps,dt=dt)
            tobe_actual=denormalize_ksim(tobe_hist,tobe_min,tobe_max)
            tobe_result=pd.DataFrame(tobe_actual,columns=tobe_names)
            tobe_result.insert(0,"Time",[f"T{i}" for i in range(len(tobe_result))])
            st.session_state.sim_results={"asis":asis_result,"tobe":tobe_result,"asis_exp":asis_exp,"tobe_exp":tobe_exp,"asis_matrix":asis.copy(),"tobe_matrix":tobe.copy(),"variables":var_names,"tobe_variables":tobe_names,"interventions":chosen.to_dict("records"),"rules":rules,"steps":steps,"dt":dt}
            st.success("Both simulations completed.")
        except Exception as exc: st.error(f"Simulation failed: {exc}")

    result=st.session_state.get("sim_results")
    if result:
        st.header("6. AS-IS vs TO-BE results")
        asis_result=result["asis"]; tobe_result=result["tobe"]
        compare_vars=[v for v in result["variables"] if v in result["tobe_variables"]]
        choice=st.multiselect("Variables to compare",compare_vars,default=compare_vars[:min(6,len(compare_vars))])
        if choice:
            chart_rows=[]
            for v in choice:
                for _,r in asis_result.iterrows(): chart_rows.append({"Time":r["Time"],"Variable":v,"Value":r[v],"Scenario":"AS-IS"})
                for _,r in tobe_result.iterrows(): chart_rows.append({"Time":r["Time"],"Variable":v,"Value":r[v],"Scenario":"TO-BE"})
            chart_df=pd.DataFrame(chart_rows)
            st.plotly_chart(px.line(chart_df,x="Time",y="Value",color="Scenario",facet_col="Variable",facet_col_wrap=2,markers=True,title="Baseline vs intervention scenarios"),use_container_width=True)
        c1,c2=st.columns(2)
        with c1:
            st.subheader("AS-IS results")
            st.dataframe(asis_result,use_container_width=True,hide_index=True)
            st.download_button("Download AS-IS CSV",asis_result.to_csv(index=False).encode(),"asis_results.csv","text/csv")
        with c2:
            st.subheader("TO-BE results")
            st.dataframe(tobe_result,use_container_width=True,hide_index=True)
            st.download_button("Download TO-BE CSV",tobe_result.to_csv(index=False).encode(),"tobe_results.csv","text/csv")
        st.download_button("Download both scenarios (JSON)",json.dumps({"AS-IS":asis_result.to_dict("records"),"TO-BE":tobe_result.to_dict("records"),"selected_interventions":result["interventions"],"rules":result["rules"]},indent=2).encode(),"asis_tobe_comparison.json","application/json")

    # Save current setup to Supabase. JSON payload stays in the row protected by RLS.
    st.header("7. Save project")
    current_payload={"problem":problem,"entities_text":entity_text,"variables_text":variables_text,"asis_matrix":asis.to_dict(),"tobe_matrix":tobe.to_dict(),"settings":settings.to_dict("records"),"steps":steps,"dt":dt,"interventions":interventions.to_dict("records")}
    save_col, delete_col=st.columns([2,1])
    if save_col.button("Save project to my workspace",type="primary",use_container_width=True):
        row={"name":project_name.strip() or "Untitled project","workspace_type":"group" if workspace_id else "personal","group_id":workspace_id,"payload":current_payload,"updated_at":datetime.utcnow().isoformat()}
        try:
            existing_id=st.session_state.get("project_id")
            if existing_id:
                sb.table("projects").update(row).eq("id",existing_id).execute()
            else:
                row["owner_id"] = uid
                response=sb.table("projects").insert(row).execute()
                if response.data: st.session_state.project_id=response.data[0]["id"]
            st.session_state.project_payload=current_payload
            st.success("Project saved to the selected workspace.")
            st.rerun()
        except Exception as exc: st.error(f"Could not save project: {exc}")
    if delete_col.button("Delete loaded project",use_container_width=True,disabled=not st.session_state.get("project_id")):
        try:
            sb.table("projects").delete().eq("id",st.session_state.project_id).execute()
            st.session_state.project_id=None; st.session_state.project_payload={}
            st.success("Project deleted."); st.rerun()
        except Exception as exc: st.error(f"Could not delete project: {exc}")

    st.header("8. Export matrices")
    export_buffer=io.BytesIO()
    with pd.ExcelWriter(export_buffer,engine="openpyxl") as writer:
        asis.to_excel(writer,sheet_name="AS-IS Matrix")
        tobe.to_excel(writer,sheet_name="TO-BE Matrix")
        settings.to_excel(writer,sheet_name="Initial Values",index=False)
        interventions.to_excel(writer,sheet_name="Interventions",index=False)
        if result:
            result["asis"].to_excel(writer,sheet_name="AS-IS Results",index=False)
            result["tobe"].to_excel(writer,sheet_name="TO-BE Results",index=False)
    st.download_button("Download full project workbook",export_buffer.getvalue(),"systems_thinking_project.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
