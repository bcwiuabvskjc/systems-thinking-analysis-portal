"""Data processing and export functions for Systems Thinking Analysis Portal."""
from __future__ import annotations
import io, re
from datetime import datetime
from typing import Any
import numpy as np
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter


def validate_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if df.empty:
        rows.append({"Severity":"Error", "Check":"Empty dataset", "Details":"The CSV has no data rows."})
    if len(df.columns) == 0:
        rows.append({"Severity":"Error", "Check":"No columns", "Details":"No columns were detected."})
    dup_cols = [str(c) for c in df.columns[df.columns.duplicated()].tolist()]
    if dup_cols:
        rows.append({"Severity":"Error", "Check":"Duplicate column names", "Details":", ".join(dup_cols)})
    missing_cells = int(df.isna().sum().sum())
    if missing_cells:
        rows.append({"Severity":"Warning", "Check":"Missing values", "Details":f"{missing_cells} missing cells across {int(df.isna().sum().gt(0).sum())} columns. Values were not imputed."})
    duplicate_rows = int(df.duplicated().sum())
    if duplicate_rows:
        rows.append({"Severity":"Warning", "Check":"Duplicate rows", "Details":f"{duplicate_rows} exact duplicate rows detected; original data is preserved."})
    blank_names = [str(c) for c in df.columns if not str(c).strip()]
    if blank_names:
        rows.append({"Severity":"Warning", "Check":"Blank column names", "Details":"One or more columns have blank names."})
    for col in df.columns:
        if df[col].dtype == object:
            s = df[col].dropna().astype(str).str.strip()
            if len(s) and (s == "").any():
                rows.append({"Severity":"Warning", "Check":f"Blank strings: {col}", "Details":f"{int((s == '').sum())} blank strings; these are not automatically replaced."})
    if not rows:
        rows.append({"Severity":"Pass", "Check":"Basic validation", "Details":"No basic structural issues detected. Method-specific checks may still be required."})
    return pd.DataFrame(rows, columns=["Severity", "Check", "Details"])


def coerce_numeric(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with columns converted only when all nonblank values parse as numbers."""
    out = df.copy()
    for col in out.columns:
        if out[col].dtype == object:
            s = out[col].astype(str).str.strip()
            nonblank = s.ne("") & s.ne("nan")
            parsed = pd.to_numeric(s.where(nonblank), errors="coerce")
            if nonblank.sum() > 0 and parsed[nonblank].notna().all():
                out[col] = parsed
    return out


def detect_cross_impact(df: pd.DataFrame, source_col: str | None = None, target_col: str | None = None, value_col: str | None = None) -> tuple[pd.DataFrame | None, str]:
    """Detect square matrix or build a matrix from explicitly mapped long-form data."""
    if source_col and target_col and value_col and all(c in df.columns for c in [source_col, target_col, value_col]):
        work = df[[source_col, target_col, value_col]].copy()
        work[value_col] = pd.to_numeric(work[value_col], errors="coerce")
        if work[[source_col, target_col, value_col]].isna().any().any():
            return None, "Mapped relationship rows contain missing or non-numeric values. Correct these before building the matrix."
        if work.duplicated([source_col, target_col]).any():
            return None, "Duplicate source-target pairs found. Resolve duplicates instead of silently aggregating them."
        mat = work.pivot(index=source_col, columns=target_col, values=value_col)
        if mat.shape[0] != mat.shape[1] or set(mat.index.astype(str)) != set(mat.columns.astype(str)):
            return None, "Long-form data must define a complete square set of source and target factors. Ensure each factor appears as both source and target; missing relationships are not assumed to be zero."
        mat = mat.reindex(index=sorted(mat.index, key=str), columns=sorted(mat.columns, key=str))
        return mat, "Built from user-mapped source, target, and influence columns. Blank relationships are not filled automatically."
    # matrix-like: row labels in first column and remaining column names are factors
    if df.shape[1] >= 2:
        first = df.columns[0]
        labels = df[first].astype(str)
        factors = [str(c) for c in df.columns[1:]]
        if len(factors) == len(labels) and set(labels) == set(factors):
            vals = df.iloc[:, 1:].copy()
            vals.columns = factors
            vals.index = labels
            numeric = vals.apply(pd.to_numeric, errors="coerce")
            if not numeric.isna().any().any():
                numeric = numeric.reindex(index=sorted(numeric.index), columns=sorted(numeric.columns))
                return numeric, "Detected a square matrix: first column treated as row factor labels; remaining columns as impact values. Confirm the mapping before interpreting."
    return None, "No unambiguous square matrix detected. If the file contains relationships, map its source, target, and impact columns in the Cross-Impact section."


def cross_impact_metrics(matrix: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    numeric = matrix.apply(pd.to_numeric, errors="raise")
    metrics = pd.DataFrame({"Factor": numeric.index.astype(str), "Influence (row sum)": numeric.sum(axis=1).to_numpy(), "Dependence (column sum)": numeric.sum(axis=0).to_numpy()})
    # Explicitly descriptive quadrants based on sample medians; not a course-specific classification.
    med_i = metrics["Influence (row sum)"].median()
    med_d = metrics["Dependence (column sum)"].median()
    def classify(r):
        hi_i = r["Influence (row sum)"] >= med_i
        hi_d = r["Dependence (column sum)"] >= med_d
        return {(True, True):"High influence / high dependence", (True, False):"High influence / low dependence", (False, True):"Low influence / high dependence", (False, False):"Low influence / low dependence"}[(hi_i, hi_d)]
    metrics["Median-based descriptive group"] = metrics.apply(classify, axis=1)
    return metrics, pd.DataFrame([{"Metric":"Influence", "Definition":"Sum across each row", "Interpretation":"Total outgoing impact under the supplied matrix convention."}, {"Metric":"Dependence", "Definition":"Sum down each column", "Interpretation":"Total incoming impact under the supplied matrix convention."}, {"Metric":"Group", "Definition":"Compare each measure with its sample median", "Interpretation":"Descriptive convenience only; replace if course notes specify another classification."}])


def build_excel(original: pd.DataFrame, filename: str, cleaned: pd.DataFrame, validation: pd.DataFrame, params: pd.DataFrame, matrix: pd.DataFrame | None, metrics: pd.DataFrame | None, numeric_summary: pd.DataFrame, notes: list[str]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        original.to_excel(writer, sheet_name="Original Data", index=False)
        cleaned.to_excel(writer, sheet_name="Cleaned Data", index=False)
        validation.to_excel(writer, sheet_name="Data Validation", index=False)
        params.to_excel(writer, sheet_name="Parameters and Assumptions", index=False)
        if matrix is not None:
            matrix.rename_axis("Factor").to_excel(writer, sheet_name="Cross-Impact Matrix")
        if metrics is not None:
            metrics.to_excel(writer, sheet_name="Influence Dependence", index=False)
        if not numeric_summary.empty:
            numeric_summary.to_excel(writer, sheet_name="Numeric Summary", index=False)
        pd.DataFrame({"Notes and Interpretation":notes}).to_excel(writer, sheet_name="Executive Summary", index=False)
    buf.seek(0)
    wb = load_workbook(buf)
    for ws in wb.worksheets:
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions if ws.max_row > 1 else "A1"
        for cell in ws[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="17365D")
            cell.alignment = Alignment(vertical="center", wrap_text=True)
        for col_cells in ws.columns:
            max_len = 0
            for cell in col_cells[:250]:
                val = "" if cell.value is None else str(cell.value)
                max_len = max(max_len, min(len(val), 60))
            ws.column_dimensions[get_column_letter(col_cells[0].column)].width = max(12, min(max_len + 2, 42))
        ws.sheet_view.showGridLines = False
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
