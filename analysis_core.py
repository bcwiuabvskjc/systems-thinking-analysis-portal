"""Course-faithful KSIM and supporting analysis functions."""
from __future__ import annotations

import io
import numpy as np
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

KSIM_METHOD = (
    "Course formula: p_i(t) = [1 + (dt/2) * sum_j((|a_ij| - a_ij) * x_j)] "
    "/ [1 + (dt/2) * sum_j((|a_ij| + a_ij) * x_j)]; "
    "x_i(t+dt) = x_i(t) ** p_i(t). Rows are target variables; columns are source variables."
)

def validate_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if df.empty:
        rows.append({"Severity": "Error", "Check": "Empty dataset", "Details": "The CSV has no data rows."})
    if len(df.columns) == 0:
        rows.append({"Severity": "Error", "Check": "No columns", "Details": "No columns were detected."})
    duplicates = df.columns[df.columns.duplicated()].tolist()
    if duplicates:
        rows.append({"Severity": "Error", "Check": "Duplicate column names", "Details": ", ".join(map(str, duplicates))})
    missing = int(df.isna().sum().sum())
    if missing:
        rows.append({"Severity": "Warning", "Check": "Missing values", "Details": f"{missing} missing cells. Values were not imputed."})
    if not rows:
        rows.append({"Severity": "Pass", "Check": "Basic validation", "Details": "No basic structural issues detected."})
    return pd.DataFrame(rows, columns=["Severity", "Check", "Details"])

def coerce_numeric(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    for col in result.columns:
        if result[col].dtype == object:
            values = result[col].astype(str).str.strip()
            nonblank = values.ne("") & values.ne("nan")
            parsed = pd.to_numeric(values.where(nonblank), errors="coerce")
            if nonblank.sum() > 0 and parsed[nonblank].notna().all():
                result[col] = parsed
    return result

def detect_cross_impact(df, source_col=None, target_col=None, value_col=None):
    if source_col and target_col and value_col and all(c in df.columns for c in [source_col, target_col, value_col]):
        work = df[[source_col, target_col, value_col]].copy()
        work[value_col] = pd.to_numeric(work[value_col], errors="coerce")
        if work.isna().any().any():
            return None, "Mapped relationship rows contain missing or non-numeric values."
        if work.duplicated([source_col, target_col]).any():
            return None, "Duplicate source-target pairs found."
        matrix = work.pivot(index=target_col, columns=source_col, values=value_col)
        if matrix.shape[0] != matrix.shape[1] or set(matrix.index.astype(str)) != set(matrix.columns.astype(str)):
            return None, "Relationship data must define a complete square set of source and target factors."
        matrix.index = matrix.index.astype(str)
        matrix.columns = matrix.columns.astype(str)
        matrix = matrix.reindex(index=sorted(matrix.index), columns=sorted(matrix.columns))
        return matrix, "Built from mapped relationship data (rows=targets, columns=sources)."
    if df.shape[1] >= 2:
        labels = df.iloc[:, 0].astype(str)
        factors = [str(c) for c in df.columns[1:]]
        if len(factors) == len(labels) and set(labels) == set(factors):
            values = df.iloc[:, 1:].copy()
            values.columns = factors
            values.index = labels
            numeric = values.apply(pd.to_numeric, errors="coerce")
            if not numeric.isna().any().any():
                numeric = numeric.reindex(index=factors, columns=factors)
                return numeric, "Detected square matrix (rows=targets, columns=sources)."
    return None, "No unambiguous square matrix detected."

def cross_impact_metrics(matrix):
    numeric = matrix.apply(pd.to_numeric, errors="raise")
    # Course convention: row i is the target, column j is the source.
    # Therefore column sums measure each source's influence; row sums measure
    # each target's dependence on all sources.
    metrics = pd.DataFrame({
        "Factor": numeric.index.astype(str),
        "Influence (column sum)": numeric.sum(axis=0).to_numpy(),
        "Dependence (row sum)": numeric.sum(axis=1).to_numpy(),
    })
    median_i = metrics["Influence (column sum)"].median()
    median_d = metrics["Dependence (row sum)"].median()
    metrics["Median-based descriptive group"] = metrics.apply(
        lambda row: ("High" if row["Influence (column sum)"] >= median_i else "Low")
        + " influence / " + ("high" if row["Dependence (row sum)"] >= median_d else "low")
        + " dependence", axis=1)
    definitions = pd.DataFrame([
        {"Metric": "Influence", "Definition": "Column sum", "Interpretation": "Total impact exerted by a source variable under the course convention."},
        {"Metric": "Dependence", "Definition": "Row sum", "Interpretation": "Total impact received by a target variable under the course convention."},
    ])
    return metrics, definitions

def run_ksim(initial_values, interaction_matrix, steps=20, dt=1.0, epsilon=1e-12):
    """Run the KSIM formula supplied in the course workbook.

    x_i(t+dt) = x_i(t) ** p_i(t)
    p_i(t) = [1 + dt/2 * sum_j((|a_ij|-a_ij)*x_j)]
             / [1 + dt/2 * sum_j((|a_ij|+a_ij)*x_j)]
    Input states are normalized to [0,1]. Matrix rows are target i and columns
    are source j, matching the supplied Excel workbook.
    """
    x0 = np.asarray(initial_values, dtype=float)
    A = np.asarray(interaction_matrix, dtype=float)
    if x0.ndim != 1 or A.shape != (len(x0), len(x0)):
        raise ValueError("Initial values must be a vector and the interaction matrix must be square with matching dimensions.")
    if not np.isfinite(x0).all() or not np.isfinite(A).all():
        raise ValueError("Inputs must contain only finite numeric values.")
    if ((x0 < 0) | (x0 > 1)).any():
        raise ValueError("Initial states must be between 0 and 1.")
    if not isinstance(steps, (int, np.integer)) or not 1 <= int(steps) <= 500:
        raise ValueError("Choose between 1 and 500 simulation steps.")
    if not np.isfinite(dt) or not 0 < float(dt) <= 10:
        raise ValueError("The time increment must be greater than 0 and at most 10.")
    x = x0.copy()
    history = [x.copy()]
    exponents = []
    for _ in range(int(steps)):
        # Keep the exact zero state at zero: 0 raised to a positive exponent remains 0.
        negative_terms = (np.abs(A) - A) * x[np.newaxis, :]
        positive_terms = (np.abs(A) + A) * x[np.newaxis, :]
        numerator = 1.0 + (float(dt) / 2.0) * negative_terms.sum(axis=1)
        denominator = 1.0 + (float(dt) / 2.0) * positive_terms.sum(axis=1)
        if (denominator <= 0).any():
            raise ValueError("KSIM exponent denominator must be positive.")
        p = numerator / denominator
        if not np.isfinite(p).all() or (p <= 0).any():
            raise ValueError("The KSIM formula produced a non-positive or non-finite exponent.")
        next_x = np.power(x, p)
        next_x = np.clip(next_x, 0.0, 1.0)
        exponents.append(p.copy())
        x = next_x
        history.append(x.copy())
    return np.asarray(history), np.asarray(exponents)

def denormalize_ksim(normalized, minimums, maximums):
    minimums = np.asarray(minimums, dtype=float)
    maximums = np.asarray(maximums, dtype=float)
    if (maximums <= minimums).any():
        raise ValueError("Each maximum must be greater than its minimum.")
    return minimums + np.asarray(normalized) * (maximums - minimums)

def build_excel(original, filename, cleaned, validation, params, matrix, metrics,
                numeric_summary, notes, ksim_results=None, ksim_exponents=None):
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        original.to_excel(writer, sheet_name="Original Data", index=False)
        cleaned.to_excel(writer, sheet_name="Cleaned Data", index=False)
        validation.to_excel(writer, sheet_name="Data Validation", index=False)
        params.to_excel(writer, sheet_name="Parameters and Assumptions", index=False)
        if matrix is not None:
            matrix.rename_axis("Target").to_excel(writer, sheet_name="Cross-Impact Matrix")
        if metrics is not None:
            metrics.to_excel(writer, sheet_name="Influence Dependence", index=False)
        if numeric_summary is not None and not numeric_summary.empty:
            numeric_summary.to_excel(writer, sheet_name="Numeric Summary", index=False)
        if ksim_results is not None:
            ksim_results.to_excel(writer, sheet_name="KSIM Results", index=False)
        if ksim_exponents is not None:
            ksim_exponents.to_excel(writer, sheet_name="KSIM Exponents", index=False)
        pd.DataFrame({"Notes and Interpretation": notes}).to_excel(writer, sheet_name="Executive Summary", index=False)
    buffer.seek(0)
    workbook = load_workbook(buffer)
    for sheet in workbook.worksheets:
        sheet.freeze_panes = "A2"
        if sheet.max_row > 1:
            sheet.auto_filter.ref = sheet.dimensions
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="17365D")
            cell.alignment = Alignment(vertical="center", wrap_text=True)
        for column_cells in sheet.columns:
            width = max((min(len(str(cell.value or "")), 60) for cell in list(column_cells)[:250]), default=10)
            sheet.column_dimensions[get_column_letter(column_cells[0].column)].width = max(12, min(width + 2, 42))
        sheet.sheet_view.showGridLines = False
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()
