"""KSIM calculations aligned to the course formula shown in the supplied workbook."""
from __future__ import annotations
import hashlib, hmac, json, os, secrets, sqlite3
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd

DB_PATH = os.environ.get("KSIM_DB_PATH", str(Path(__file__).with_name("ksim_portal.sqlite3")))

KSIM_FORMULA = (
    "x_i(t+dt) = x_i(t) ** p_i(t);  "
    "p_i(t) = [1 + (dt/2) * sum_j((|a_ij| - a_ij) * x_j(t))] / "
    "[1 + (dt/2) * sum_j((|a_ij| + a_ij) * x_j(t))]. "
    "Rows are target variables i; columns are source variables j. States are in [0, 1]."
)


def validate_model(variables: pd.DataFrame, matrix: pd.DataFrame) -> None:
    required = {"Code", "Entity", "Relevant attribute", "Initial value", "Start time"}
    missing = required - set(variables.columns)
    if missing:
        raise ValueError(f"Variable table is missing columns: {', '.join(sorted(missing))}")
    if variables.empty:
        raise ValueError("Add at least one variable before running the simulation.")
    codes = variables["Code"].astype(str).str.strip().tolist()
    if any(not c for c in codes) or len(set(codes)) != len(codes):
        raise ValueError("Every variable needs a unique, non-empty code (for example X1, X2).")
    if matrix.shape != (len(codes), len(codes)):
        raise ValueError("The cross-impact matrix must be square and match the number of variables.")
    if list(map(str, matrix.index)) != codes or list(map(str, matrix.columns)) != codes:
        raise ValueError("Matrix row and column codes must match the variable codes in the same order.")
    values = pd.to_numeric(variables["Initial value"], errors="coerce").to_numpy(float)
    starts = pd.to_numeric(variables["Start time"], errors="coerce").to_numpy(float)
    A = matrix.apply(pd.to_numeric, errors="coerce").to_numpy(float)
    if not np.isfinite(values).all() or ((values < 0) | (values > 1)).any():
        raise ValueError("Initial values must be numeric and between 0 and 1, as required by the supplied KSIM formulation.")
    if not np.isfinite(starts).all() or (starts < 0).any() or (starts != np.floor(starts)).any():
        raise ValueError("Start time must be a non-negative whole number.")
    if not np.isfinite(A).all():
        raise ValueError("Every cross-impact matrix cell must contain a finite number.")


def run_ksim_course(variables: pd.DataFrame, matrix: pd.DataFrame, steps: int, dt: float = 1.0,
                    interventions: pd.DataFrame | None = None):
    """Run the course formula, supporting variables introduced at a later time.

    A variable with Start time=k is absent before k, starts at Initial value at k,
    and participates in exponents from k onward. An intervention sets the selected
    variable to a specified value at the beginning of the specified time point.
    Returns state table, exponent table, and numeric arrays for downstream plotting.
    """
    validate_model(variables, matrix)
    if not isinstance(steps, int) or steps < 1 or steps > 200:
        raise ValueError("Simulation periods must be between 1 and 200.")
    if not np.isfinite(dt) or dt <= 0:
        raise ValueError("Δt must be greater than zero.")
    df = variables.reset_index(drop=True).copy()
    codes = df["Code"].astype(str).tolist()
    n = len(codes)
    initials = pd.to_numeric(df["Initial value"]).to_numpy(float)
    starts = pd.to_numeric(df["Start time"]).to_numpy(int)
    A = matrix.to_numpy(float)
    states = np.full((steps + 1, n), np.nan, dtype=float)
    exps = np.full((steps + 1, n), np.nan, dtype=float)
    nums = np.full((steps + 1, n), np.nan, dtype=float)
    dens = np.full((steps + 1, n), np.nan, dtype=float)
    active = np.zeros(n, dtype=bool)

    intervention_rows = []
    if interventions is not None and not interventions.empty:
        for _, r in interventions.iterrows():
            code = str(r.get("Variable code", "")).strip()
            time = int(r.get("Time", 0))
            value = float(r.get("Set value", 0))
            if code not in codes:
                raise ValueError(f"Intervention refers to unknown variable code {code!r}.")
            if not 0 <= time <= steps:
                raise ValueError(f"Intervention time for {code} must be between T0 and T{steps}.")
            if not 0 <= value <= 1:
                raise ValueError("Intervention values must be between 0 and 1.")
            intervention_rows.append((codes.index(code), time, value))

    for t in range(steps + 1):
        # Activate variables scheduled to enter at this time.
        for i in range(n):
            if starts[i] == t and not active[i]:
                states[t, i] = initials[i]
                active[i] = True
        # Carry forward the prior state for already-active variables.
        if t > 0:
            for i in range(n):
                if active[i] and np.isnan(states[t, i]) and not np.isnan(states[t-1, i]):
                    states[t, i] = states[t-1, i]
        # Apply interventions at the beginning of time t, before calculating P_i(t).
        for i, itime, val in intervention_rows:
            if itime == t:
                if not active[i]:
                    active[i] = True
                    states[t, i] = val
                else:
                    states[t, i] = val
        x = np.nan_to_num(states[t], nan=0.0)
        for i in range(n):
            if not active[i] or np.isnan(states[t, i]):
                continue
            # Formula from the provided course reference; inactive sources contribute zero.
            numerator = 1.0 + (dt / 2.0) * np.sum((np.abs(A[i, :]) - A[i, :]) * x)
            denominator = 1.0 + (dt / 2.0) * np.sum((np.abs(A[i, :]) + A[i, :]) * x)
            if denominator == 0:
                raise ValueError(f"Zero denominator for {codes[i]} at T{t}.")
            p = numerator / denominator
            nums[t, i], dens[t, i], exps[t, i] = numerator, denominator, p
            if t < steps:
                # Update after calculating the exponent at current time. Keep exact zero as zero.
                states[t+1, i] = 0.0 if states[t, i] == 0 else float(states[t, i] ** p)
    # Apply final scheduled activation if a variable starts at T=steps, then calculate its P.
    # (Already handled in the loop above.)
    return states, exps, nums, dens


def make_state_frame(variables: pd.DataFrame, states: np.ndarray) -> pd.DataFrame:
    base = variables[["Entity", "Relevant attribute", "Code"]].copy().reset_index(drop=True)
    for t in range(states.shape[0]):
        base[f"T{t}"] = states[t, :]
    return base


def make_calculation_frame(variables: pd.DataFrame, nums: np.ndarray, dens: np.ndarray, exps: np.ndarray) -> pd.DataFrame:
    base = variables[["Entity", "Relevant attribute", "Code"]].copy().reset_index(drop=True)
    for t in range(exps.shape[0]):
        base[f"T{t} · Pᵢ Num"] = nums[t, :]
        base[f"T{t} · Pᵢ Den"] = dens[t, :]
        base[f"T{t} · Pᵢ"] = exps[t, :]
    return base


def password_hash(password: str, salt: bytes | None = None) -> tuple[bytes, bytes]:
    if len(password) < 10:
        raise ValueError("Use a password with at least 10 characters.")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310_000)
    return salt, digest


def verify_password(password: str, salt: bytes, expected: bytes) -> bool:
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310_000)
    return hmac.compare_digest(actual, expected)


def db_connect():
    con = sqlite3.connect(DB_PATH, timeout=20, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with db_connect() as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, salt BLOB NOT NULL, password_hash BLOB NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        con.execute("CREATE TABLE IF NOT EXISTS projects (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, name TEXT NOT NULL, payload TEXT NOT NULL, updated_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(user_id,name), FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE)")
        con.commit()


def register_user(username: str, password: str) -> None:
    username = username.strip().lower()
    if len(username) < 3 or len(username) > 40 or not username.replace("_", "").replace("-", "").isalnum():
        raise ValueError("Username must be 3–40 characters and use letters, numbers, _ or - only.")
    salt, digest = password_hash(password)
    try:
        with db_connect() as con:
            con.execute("INSERT INTO users(username,salt,password_hash) VALUES(?,?,?)", (username, salt, digest))
            con.commit()
    except sqlite3.IntegrityError:
        raise ValueError("That username already exists. Choose another username or sign in.")


def authenticate_user(username: str, password: str):
    with db_connect() as con:
        row = con.execute("SELECT id, username, salt, password_hash FROM users WHERE username=?", (username.strip().lower(),)).fetchone()
    if row and verify_password(password, row["salt"], row["password_hash"]):
        return {"id": row["id"], "username": row["username"]}
    return None


def save_project(user_id: int, name: str, payload: dict[str, Any]) -> None:
    name = name.strip()
    if not name or len(name) > 100:
        raise ValueError("Project name must be between 1 and 100 characters.")
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    with db_connect() as con:
        con.execute("INSERT INTO projects(user_id,name,payload,updated_at) VALUES(?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(user_id,name) DO UPDATE SET payload=excluded.payload, updated_at=CURRENT_TIMESTAMP", (user_id, name, encoded))
        con.commit()


def list_projects(user_id: int):
    with db_connect() as con:
        rows = con.execute("SELECT id,name,updated_at FROM projects WHERE user_id=? ORDER BY updated_at DESC, name", (user_id,)).fetchall()
    return [dict(r) for r in rows]


def load_project(user_id: int, project_id: int):
    with db_connect() as con:
        row = con.execute("SELECT name,payload,updated_at FROM projects WHERE id=? AND user_id=?", (project_id, user_id)).fetchone()
    if not row:
        raise ValueError("Project not found or you do not have permission to access it.")
    return row["name"], json.loads(row["payload"]), row["updated_at"]


def delete_project(user_id: int, project_id: int):
    with db_connect() as con:
        cur = con.execute("DELETE FROM projects WHERE id=? AND user_id=?", (project_id, user_id))
        con.commit()
    if cur.rowcount == 0:
        raise ValueError("Project not found or you do not have permission to delete it.")
