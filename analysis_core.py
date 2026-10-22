from __future__ import annotations
import uuid
import numpy as np
import pandas as pd

KSIM_METHOD = """Course KSIM update:
x_i(t + Δt) = x_i(t) ** p_i(t)
p_i(t) = [1 + (Δt/2) Σ_j (|a_ij| - a_ij) x_j] /
         [1 + (Δt/2) Σ_j (|a_ij| + a_ij) x_j]
Rows are target variables i; columns are source variables j. Initial states are normalized to [0, 1]."""

def new_project(name="My KSIM model"):
    variables=["Parthenium","Asthma incidence","Happiness","Government response","Hospital admissions","Expert committee"]
    # Illustrative matrix only: replace with the exact coefficients from the course workbook.
    A=pd.DataFrame([[0,.35,-.25,-.15,0,-.1],[.25,0,-.1,-.05,.25,-.1],[-.2,-.15,0,.25,-.2,.15],[-.3,-.1,.2,0,.15,.3],[.15,.25,-.2,.2,0,.1],[-.1,-.1,.15,.3,.15,0]],index=variables,columns=variables)
    return {"id":str(uuid.uuid4()),"name":name,"variables":variables,"initial":[.5,.35,.35,.3,.3,.1],"matrix":A.to_dict(orient="split"),"steps":15,"dt":1.0,"step":1,"results":None,"exponents":None,"updated_at":None}

def matrix_from_project(project):
    stored=project.get("matrix"); variables=project.get("variables",[])
    if isinstance(stored,dict) and {"index","columns","data"}.issubset(stored):
        A=pd.DataFrame(stored["data"],index=stored["index"],columns=stored["columns"])
    else: A=pd.DataFrame(stored,index=variables,columns=variables)
    A.index=A.index.astype(str); A.columns=A.columns.astype(str)
    return A.loc[variables,variables].astype(float)

def validate_project(project,require_results=False):
    required=["id","name","variables","initial","matrix"]
    missing=[k for k in required if k not in project]
    if missing: raise ValueError("Project JSON is missing: "+", ".join(missing))
    v=project["variables"]
    if not isinstance(v,list) or not 2<=len(v)<=20: raise ValueError("Project must have 2–20 variables.")
    if len(set(v))!=len(v) or any(not isinstance(x,str) or not x.strip() for x in v): raise ValueError("Variable names must be unique and non-empty.")
    x=np.asarray(project["initial"],dtype=float)
    if x.shape!=(len(v),) or not np.isfinite(x).all() or ((x<0)|(x>1)).any(): raise ValueError("Initial states must be between 0 and 1.")
    A=matrix_from_project(project)
    if A.shape!=(len(v),len(v)) or not np.isfinite(A.to_numpy()).all(): raise ValueError("Matrix must be square and finite.")
    steps=project.get("steps",15)
    if not isinstance(steps,(int,np.integer)) or not 1<=int(steps)<=200: raise ValueError("Time steps must be an integer from 1 to 200.")
    dt=float(project.get("dt",1))
    if not np.isfinite(dt) or not 0<dt<=10: raise ValueError("Δt must be greater than 0 and at most 10.")
    if require_results and not project.get("results"): raise ValueError("No saved simulation results.")

def cross_impact_metrics(matrix):
    A=matrix.astype(float)
    # With rows=targets and columns=sources: source influence is column total; target dependence is row total.
    return pd.DataFrame({"Variable":A.index,"Dependence (absolute row sum)":A.abs().sum(axis=1).to_numpy(),"Influence (absolute column sum)":A.abs().sum(axis=0).reindex(A.index).to_numpy()})

def run_ksim(initial_values,interaction_matrix,steps=20,dt=1.0):
    """Apply the course KSIM formula; returns state history and exponents per step."""
    x0=np.asarray(initial_values,dtype=float); A=np.asarray(interaction_matrix,dtype=float)
    if x0.ndim!=1 or A.shape!=(len(x0),len(x0)): raise ValueError("Initial values and square matrix dimensions must match.")
    if not np.isfinite(x0).all() or not np.isfinite(A).all(): raise ValueError("Inputs must be finite numeric values.")
    if ((x0<0)|(x0>1)).any(): raise ValueError("Initial states must be between 0 and 1.")
    if not isinstance(steps,(int,np.integer)) or not 1<=int(steps)<=500: raise ValueError("Choose 1–500 steps.")
    if not np.isfinite(dt) or not 0<float(dt)<=10: raise ValueError("Δt must be greater than 0 and at most 10.")
    x=x0.copy(); history=[x.copy()]; exponents=[]
    for _ in range(int(steps)):
        negative=(np.abs(A)-A)*x[np.newaxis,:]
        positive=(np.abs(A)+A)*x[np.newaxis,:]
        numerator=1+(float(dt)/2)*negative.sum(axis=1)
        denominator=1+(float(dt)/2)*positive.sum(axis=1)
        if (denominator<=0).any(): raise ValueError("KSIM exponent denominator must be positive.")
        p=numerator/denominator
        if not np.isfinite(p).all() or (p<=0).any(): raise ValueError("KSIM formula produced an invalid exponent.")
        x=np.clip(np.power(x,p),0,1); exponents.append(p.copy()); history.append(x.copy())
    return np.asarray(history),np.asarray(exponents)
