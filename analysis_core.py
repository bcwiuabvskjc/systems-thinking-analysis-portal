"""Analysis functions for Systems Thinking Analysis Portal, including KSIM."""
from __future__ import annotations

import io
import numpy as np
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter


KSIM_METHOD = (
    "Documented simplified KSIM-style variant: normalize each variable to [0,1]. "
    "For target i, calculate positive and negative exposure from signed interaction "
    "coefficients weighted by current source-variable states. The exponent P_i is "
    "(negative exposure + epsilon)/(positive exposure + epsilon). Update using "
    "x_i(next)=x_i(current)**(P_i*dt). This is not guaranteed to match every "
    "published KSIM formulation or a course-specific variant."
)


def validate_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    rows = []

    if df.empty:
        rows.append({
            "Severity": "Error",
            "Check": "Empty dataset",
            "Details": "The CSV has no data rows."
        })

    if len(df.columns) == 0:
        rows.append({
            "Severity": "Error",
            "Check": "No columns",
            "Details": "No columns were detected."
        })

    dup_cols = [
        str(c) for c in df.columns[df.columns.duplicated()].tolist()
    ]
    if dup_cols:
        rows.append({
            "Severity": "Error",
            "Check": "Duplicate column names",
            "Details": ", ".join(dup_cols)
        })

    missing_cells = int(df.isna().sum().sum())
    if missing_cells:
        rows.append({
            "Severity": "Warning",
            "Check": "Missing values",
            "Details": (
                f"{missing_cells} missing cells. "
                "Values were not imputed."
            )
        })

    if not rows:
        rows.append({
            "Severity": "Pass",
            "Check": "Basic validation",
            "Details": "No basic structural issues detected."
        })

    return pd.DataFrame(
        rows, columns=["Severity", "Check", "Details"]
    )


def coerce_numeric(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    for col in out.columns:
        if out[col].dtype == object:
            s = out[col].astype(str).str.strip()
            nonblank = s.ne("") & s.ne("nan")
            parsed = pd.to_numeric(
                s.where(nonblank), errors="coerce"
            )

            if nonblank.sum() > 0 and parsed[nonblank].notna().all():
                out[col] = parsed

    return out


def detect_cross_impact(
    df, source_col=None, target_col=None, value_col=None
):
    # Relationship-list format
    if (
        source_col and target_col and value_col
        and all(c in df.columns
                for c in [source_col, target_col, value_col])
    ):
        work = df[[source_col, target_col, value_col]].copy()
        work[value_col] = pd.to_numeric(
            work[value_col], errors="coerce"
        )

        if work.isna().any().any():
            return None, (
