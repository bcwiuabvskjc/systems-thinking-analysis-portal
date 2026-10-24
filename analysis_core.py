"""Professor-aligned KSIM engine and matrix utilities for the Systems Thinking Portal."""
from __future__ import annotations
from itertools import combinations
from io import BytesIO
from typing import Any
import numpy as np
import pandas as pd

KSIM_FORMULA = (
    "p_i(t) = [1 + (dt/2) * Σ_j (|a_ij| - a_ij) x_j(t)] / "
    "[1 + (dt/2) * Σ_j (|a_ij| + a_ij) x_j(t)];  x_i(t+dt) = x_i(t) ** p_i(t)"
)


def validate_matrix(matrix: pd.DataFrame, min_vars: int = 2, max_vars: int = 20) -> pd.DataFrame:
    checks = []
    if not isinstance(matrix, pd.DataFrame):
        return pd.DataFrame([{"Status":"Error", "Check":"Matrix format", "Details":"Expected a pandas DataFrame."}])
    names = [str(c).strip() for c in matrix.columns]
    idx = [str(i).strip() for i in matrix.index]
    if matrix.shape[0] != matrix.shape[1]:
        checks.append(("Error", "Square matrix", f"Matrix has {matrix.shape[0]} rows and {matrix.shape[1]} columns; they must match."))
    if names != idx:
        checks.append(("Error", "Matching labels", "Row labels and column labels must contain the same variable names in the same order."))
    if len(set(names)) != len(names):
        checks.append(("Error", "Unique names", "Variable names must be unique."))
    if not min_vars <= len(names) <= max_vars:
        checks.append(("Error", "Variable count", f"Use between {min_vars} and {max_vars} variables."))
    try:
        values = matrix.apply(pd.to_numeric, errors="raise").to_numpy(float)
        if not np.isfinite(values).all():
            checks.append(("Error", "Finite numeric values", "Every matrix cell must be a finite number."))
        if (np.abs(values) > 1).any():
            checks.append(("Error", "Impact range", "Each impact must be between -1 and +1."))
    except Exception:
        checks.append(("Error", "Numeric values", "Every matrix cell must contain a number."))
    if not checks:
        checks.append(("Pass", "Matrix structure", "Square matrix, matching labels and valid numeric impact values."))
    return pd.DataFrame(checks, columns=["Status", "Check", "Details"])


def parse_matrix_upload(uploaded_file) -> tuple[pd.DataFrame, dict[str, Any], str]:
    """Read CSV/XLSX. Excel may contain 'AS-IS Matrix' and 'Initial Values' sheets."""
    filename = uploaded_file.name.lower()
    initial = {}
    if filename.endswith(".csv"):
        raw = pd.read_csv(uploaded_file)
        matrix = _matrix_from_frame(raw)
        return matrix, initial, "Read the CSV matrix."
    if filename.endswith((".xlsx", ".xlsm")):
        book = pd.ExcelFile(uploaded_file)
        sheet = "AS-IS Matrix" if "AS-IS Matrix" in book.sheet_names else book.sheet_names[0]
        raw = pd.read_excel(book, sheet_name=sheet)
        matrix = _matrix_from_frame(raw)
        if "Initial Values" in book.sheet_names:
            init_df = pd.read_excel(book, sheet_name="Initial Values")
            if {"Variable", "Initial value"}.issubset(init_df.columns):
                for _, r in init_df.iterrows():
                    nm = str(r["Variable"]).strip()
                    if nm and nm.lower() != "nan":
                        initial[nm] = {k: _safe_float(r.get(k), d) for k, d in [("Initial value", 0.5), ("Minimum", 0.0), ("Maximum", 1.0)]}
        return matrix, initial, f"Read matrix from sheet '{sheet}'."
    raise ValueError("Upload a .csv or .xlsx file.")


def _safe_float(v, default):
    try:
        n = float(v)
        return n if np.isfinite(n) else default
    except Exception:
        return default


def _matrix_from_frame(frame: pd.DataFrame) -> pd.DataFrame:
    df = frame.copy().dropna(how="all").dropna(axis=1, how="all")
    if df.empty:
        raise ValueError("The uploaded file does not contain a matrix.")
    first = str(df.columns[0]).strip().lower()
    if first in {"variable", "factor", "entity", "unnamed: 0", "index"}:
        df = df.set_index(df.columns[0])
    elif df.shape[1] >= 2 and not pd.api.types.is_numeric_dtype(df.iloc[:, 0]):
        # Treat first column as row labels when it looks like labels, not a numeric matrix column.
        df = df.set_index(df.columns[0])
    df.index = df.index.map(lambda x: str(x).strip())
    df.columns = df.columns.map(lambda x: str(x).strip())
    if any(not x or x.lower() == "nan" for x in df.index) or any(not x or x.lower() == "nan" for x in df.columns):
        raise ValueError("Every row and column needs a variable name.")
    df = df.apply(pd.to_numeric, errors="raise")
    if list(df.index) != list(df.columns):
        if set(df.index) == set(df.columns):
            df = df.reindex(index=list(df.columns))
        else:
            raise ValueError("Row and column variable names must match exactly. Use the provided template.")
    return df.astype(float)


def make_template_xlsx(variable_names: list[str] | None = None) -> bytes:
    names = variable_names or ["Variable 1", "Variable 2", "Variable 3", "Variable 4"]
    names = [str(n).strip() for n in names if str(n).strip()]
    if len(names) < 2: names = ["Variable 1", "Variable 2"]
    matrix = pd.DataFrame(np.zeros((len(names), len(names))), index=names, columns=names)
    matrix.index.name = "Variable"
    settings = pd.DataFrame({"Variable": names, "Initial value": [0.5]*len(names), "Minimum": [0.0]*len(names), "Maximum": [1.0]*len(names)})
    notes = pd.DataFrame({"Field": ["Matrix convention", "Positive impact", "Negative impact", "Zero", "Range", "KSIM formula"], "Meaning": ["Rows = affected/target variable; columns = influencing/source variable.", "Reinforcing influence on the row variable.", "Inhibiting influence on the row variable.", "No direct influence specified.", "Use values from -1 to +1.", KSIM_FORMULA]})
    out = BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        matrix.to_excel(writer, sheet_name="AS-IS Matrix")
        settings.to_excel(writer, sheet_name="Initial Values", index=False)
        notes.to_excel(writer, sheet_name="Read Me", index=False)
    return out.getvalue()


def matrix_to_payload(df: pd.DataFrame) -> dict:
    return {"index": list(map(str, df.index)), "columns": list(map(str, df.columns)), "data": df.astype(float).values.tolist()}


def matrix_from_payload(payload: dict | None) -> pd.DataFrame | None:
    if not payload or not all(k in payload for k in ("index", "columns", "data")):
        return None
    try:
        return pd.DataFrame(payload["data"], index=payload["index"], columns=payload["columns"], dtype=float)
    except Exception:
        return None


def professor_ksim_step(x: np.ndarray, a: np.ndarray, dt: float = 1.0) -> tuple[np.ndarray, pd.DataFrame]:
    """One professor-workbook KSIM step. Matrix rows=targets; columns=sources."""
    x = np.asarray(x, dtype=float)
    a = np.asarray(a, dtype=float)
    if a.shape != (len(x), len(x)):
        raise ValueError("Matrix dimensions must match the state vector.")
    if not np.isfinite(x).all() or not np.isfinite(a).all():
        raise ValueError("States and impacts must be finite.")
    if (x < 0).any() or (x > 1).any():
        raise ValueError("Normalized KSIM states must be between 0 and 1.")
    pos_coeff = np.abs(a) + a
    neg_coeff = np.abs(a) - a
    numerator = 1.0 + (dt / 2.0) * (neg_coeff @ x)
    denominator = 1.0 + (dt / 2.0) * (pos_coeff @ x)
    exponent = numerator / denominator
    next_x = np.power(x, exponent)
    detail = pd.DataFrame({"Current state": x, "Numerator": numerator, "Denominator": denominator, "Exponent": exponent, "Next state": next_x})
    return next_x, detail


def simulate_ksim(
    names: list[str], matrix: pd.DataFrame, initial_values: dict[str, float], steps: int = 10, dt: float = 1.0,
    activations: list[dict] | None = None, relationship_events: list[dict] | None = None,
    minimums: dict[str, float] | None = None, maximums: dict[str, float] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Simulate states. New variables are set at their specified state time; relationships activate at that time."""
    if list(matrix.index) != names or list(matrix.columns) != names:
        raise ValueError("Matrix labels must exactly match the simulation variable order.")
    a_base = matrix.to_numpy(float)
    if a_base.shape[0] != a_base.shape[1] or not np.isfinite(a_base).all():
        raise ValueError("The simulation matrix must be finite and square.")
    if (np.abs(a_base) > 1).any():
        raise ValueError("Impacts must be between -1 and +1.")
    lo = {n: float((minimums or {}).get(n, 0.0)) for n in names}
    hi = {n: float((maximums or {}).get(n, 1.0)) for n in names}
    x = np.zeros(len(names), dtype=float)
    for i, n in enumerate(names):
        mn, mx = lo[n], hi[n]
        if not np.isfinite([mn, mx]).all() or mx <= mn:
            raise ValueError(f"Invalid minimum/maximum for {n}.")
        val = float(initial_values.get(n, mn))
        if not np.isfinite(val) or val < mn or val > mx:
            raise ValueError(f"Initial value for {n} must be between {mn} and {mx}.")
        x[i] = (val - mn) / (mx - mn)
    activations = activations or []
    relationship_events = relationship_events or []
    name_index = {n: i for i, n in enumerate(names)}
    activation_by_time: dict[int, list[dict]] = {}
    for ev in activations:
        t = int(ev.get("start_period", 0))
        if t < 0 or t > steps: raise ValueError("Intervention start periods must be within T0 and the final simulation period.")
        activation_by_time.setdefault(t, []).append(ev)
    event_by_time: dict[int, list[dict]] = {}
    for ev in relationship_events:
        t = int(ev.get("start_period", 0))
        if t < 0 or t > steps: raise ValueError("Relationship start periods must be within the simulation horizon.")
        event_by_time.setdefault(t, []).append(ev)
    states, details = [], []
    a_current = a_base.copy()
    for t in range(steps + 1):
        # Intervention variables become active at the stated state time (e.g. T4=0.3).
        for ev in activation_by_time.get(t, []):
            nm = str(ev["variable"])
            if nm not in name_index: raise ValueError(f"Unknown intervention variable: {nm}")
            mn, mx = lo[nm], hi[nm]
            x[name_index[nm]] = (float(ev["initial_value"]) - mn) / (mx - mn)
        for ev in event_by_time.get(t, []):
            target, source, impact = str(ev["target"]), str(ev["source"]), float(ev["impact"])
            if target not in name_index or source not in name_index: raise ValueError(f"Unknown relationship variable in {target} ← {source}.")
            a_current[name_index[target], name_index[source]] = impact
        states.append(x.copy())
        if t == steps: break
        next_x, step_detail = professor_ksim_step(x, a_current, dt)
        for i, nm in enumerate(names):
            details.append({"From time": f"T{t}", "To time": f"T{t+1}", "Variable": nm,
                            "Current state (normalized)": x[i], "Numerator": step_detail.iloc[i]["Numerator"],
                            "Denominator": step_detail.iloc[i]["Denominator"], "Exponent": step_detail.iloc[i]["Exponent"],
                            "Next state (normalized)": next_x[i], "Matrix active at step": f"T{t}"})
        x = next_x
    states_arr = np.asarray(states)
    # Return original-scale state values and normalized detail values, with states by T0..Tn.
    actual = np.column_stack([[lo[n] + states_arr[:, i] * (hi[n] - lo[n]) for i, n in enumerate(names)][i] for i, n in enumerate(names)])
    result = pd.DataFrame(actual, columns=names)
    result.insert(0, "Time", [f"T{i}" for i in range(steps + 1)])
    return result, pd.DataFrame(details)


def validate_reference_first_iteration() -> dict:
    """Reference test from professor workbook's AS-IS_Parthenium sheet (T0 -> T1)."""
    names = ["X1", "X2", "X3", "X4", "X5", "X6"]
    x = np.array([0.5, 0.35, 0.35, 0.3, 0.3, 0.1], dtype=float)
    # Matrix cells G18:L23 from workbook; x7 is absent in the AS-IS sheet and contributes zero.
    a = np.array([
        [0.3, 0, 0, -0.1, 0, 0],
        [0.7, -0.2, -0.2, -0.3, 0, -0.1],
        [0, -0.8, 0.4, 0.1, -0.7, 0],
        [0.6, 0.7, -0.5, -0.2, 0.5, 0.6],
        [0.7, 0.3, -0.1, -0.1, -0.2, -0.1],
        [0.5, 0.5, -0.5, 0.7, 0.6, 0.5],
    ], dtype=float)
    next_x, details = professor_ksim_step(x, a, 1.0)
    expected_num = np.array([1.03, 1.24, 1.49, 1.235, 1.135, 1.175])
    expected_den = np.array([1.15, 1.35, 1.17, 1.755, 1.455, 1.865])
    expected_state = np.array([0.5375041601962823, 0.3812572013307588, 0.2626447390717447, 0.42859617449632537, 0.39094768158173915, 0.23440841070163995])
    return {"passed": bool(np.allclose(details["Numerator"], expected_num, atol=1e-12) and np.allclose(details["Denominator"], expected_den, atol=1e-12) and np.allclose(next_x, expected_state, atol=1e-12)),
            "numerators": details["Numerator"].tolist(), "denominators": details["Denominator"].tolist(),
            "exponents": details["Exponent"].tolist(), "next_states": next_x.tolist(),
            "expected_next_states": expected_state.tolist()}


def validate_reference_intervention() -> dict:
    """Checks the professor workbook's intervention scenario, including beetle activation at T4."""
    base = validate_reference_first_iteration()
    names = ["X1", "X2", "X3", "X4", "X5", "X6", "X7"]
    a = np.zeros((7, 7), dtype=float)
    a[:6, :6] = np.array([
        [0.3, 0, 0, -0.1, 0, 0],
        [0.7, -0.2, -0.2, -0.3, 0, -0.1],
        [-0.7, -0.8, 0.4, 0.1, -0.7, 0],
        [0.6, 0.7, -0.5, -0.2, 0.5, 0.6],
        [0.7, 0.3, -0.1, -0.1, -0.2, -0.1],
        [0.5, 0.5, -0.5, 0.7, 0.6, 0.5],
    ])
    a[0, 6] = -0.9
    a[2, 6] = 0.1
    a[3, 6] = -0.3
    a[5, 6] = -0.3
    a[6, 6] = 0.5
    x = np.array([0.5, 0.35, 0.35, 0.3, 0.3, 0.1, 0.0])
    next_x, detail = professor_ksim_step(x, a, 1.0)
    expected = np.array([0.5375041601962823, 0.3812572013307588, 0.19185751046792543, 0.42859617449632537, 0.39094768158173915, 0.23440841070163995, 0.0])
    names7 = ["X1", "X2", "X3", "X4", "X5", "X6", "X7"]
    mat = pd.DataFrame(a, index=names7, columns=names7)
    vals = dict(zip(names7, [0.5, 0.35, 0.35, 0.3, 0.3, 0.1, 0.0]))
    activation = [{"variable":"X7", "start_period":4, "initial_value":0.3}]
    events = []
    for i, target in enumerate(names7):
        for j, source in enumerate(names7):
            # Only the intervention-specific matrix changes; all become active from T0 as in the workbook.
            if i == 2 and j == 0: events.append({"target":target,"source":source,"impact":-0.7,"start_period":0})
            elif i == 0 and j == 6: events.append({"target":target,"source":source,"impact":-0.9,"start_period":0})
            elif i == 2 and j == 6: events.append({"target":target,"source":source,"impact":0.1,"start_period":0})
            elif i == 3 and j == 6: events.append({"target":target,"source":source,"impact":-0.3,"start_period":0})
            elif i == 5 and j == 6: events.append({"target":target,"source":source,"impact":-0.3,"start_period":0})
            elif i == 6 and j == 6: events.append({"target":target,"source":source,"impact":0.5,"start_period":0})
    result, _ = simulate_ksim(names7, mat, vals, 5, 1.0, activations=activation, relationship_events=events, minimums={n:0 for n in names7}, maximums={n:1 for n in names7})
    first_actual = result.iloc[1][names7].to_numpy(float)
    beetle_at_t4 = float(result.loc[result["Time"]=="T4", "X7"].iloc[0])
    expected_t5 = np.array([0.5922056258533724, 0.44322365238673506, 2.5943680219353595e-10, 0.9353030285206491, 0.6771921315375133, 0.9582946861471277, 0.3510127001782277])
    actual_t5 = result.loc[result["Time"]=="T5", names7].iloc[0].to_numpy(float)
    return {
        "passed_first_intervention_step": bool(np.allclose(first_actual, expected, atol=1e-12)),
        "passed_beetle_activation_t4": bool(np.isclose(beetle_at_t4, 0.3, atol=1e-12)),
        "passed_t4_to_t5_reference": bool(np.allclose(actual_t5, expected_t5, atol=1e-8)),
        "first_step_actual": first_actual.tolist(), "first_step_expected": expected.tolist(),
        "beetle_at_T4": beetle_at_t4, "T5_actual": actual_t5.tolist(), "T5_expected": expected_t5.tolist()
    }
