"""
03 — Data Quality Monitor
Runs automated quality checks on uploaded datasets:
completeness, uniqueness, freshness, distribution drift.
"""

import io
import json
from datetime import datetime
from typing import Optional

import pandas as pd
import numpy as np
from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel

router = APIRouter()


def compute_quality_report(df: pd.DataFrame, filename: str) -> dict:
    total_rows = len(df)
    total_cols = len(df.columns)
    total_cells = total_rows * total_cols
    null_cells = int(df.isnull().sum().sum()) + int((df == "").sum().sum())

    column_reports = []
    alerts = []

    for col in df.columns:
        series = df[col].replace("", pd.NA)
        null_count = int(series.isna().sum())
        completeness = round((1 - null_count / total_rows) * 100, 1) if total_rows > 0 else 0
        non_null = series.dropna()
        unique_count = int(non_null.nunique())
        uniqueness = round((unique_count / len(non_null)) * 100, 1) if len(non_null) > 0 else 0
        duplicate_count = int(len(non_null) - unique_count)

        col_report = {
            "column": col,
            "dtype_detected": str(df[col].dtype),
            "total_values": total_rows,
            "null_count": null_count,
            "completeness_pct": completeness,
            "unique_count": unique_count,
            "uniqueness_pct": uniqueness,
            "duplicate_count": duplicate_count,
        }

        # Try numeric analysis
        try:
            numeric = pd.to_numeric(non_null, errors="raise")
            col_report["numeric_stats"] = {
                "mean": round(float(numeric.mean()), 2),
                "median": round(float(numeric.median()), 2),
                "std": round(float(numeric.std()), 2),
                "min": round(float(numeric.min()), 2),
                "max": round(float(numeric.max()), 2),
                "q1": round(float(numeric.quantile(0.25)), 2),
                "q3": round(float(numeric.quantile(0.75)), 2),
            }
            iqr = numeric.quantile(0.75) - numeric.quantile(0.25)
            lower = numeric.quantile(0.25) - 1.5 * iqr
            upper = numeric.quantile(0.75) + 1.5 * iqr
            outliers = int(((numeric < lower) | (numeric > upper)).sum())
            col_report["outlier_count"] = outliers
            if outliers > total_rows * 0.05:
                alerts.append({
                    "column": col, "type": "outliers",
                    "severity": "warning",
                    "message": f"{outliers} outliers detected ({round(outliers/total_rows*100,1)}% of data)"
                })
        except (ValueError, TypeError):
            pass

        # String analysis
        if df[col].dtype == "object":
            lengths = non_null.astype(str).str.len()
            col_report["string_stats"] = {
                "avg_length": round(float(lengths.mean()), 1) if len(lengths) > 0 else 0,
                "min_length": int(lengths.min()) if len(lengths) > 0 else 0,
                "max_length": int(lengths.max()) if len(lengths) > 0 else 0,
                "top_values": non_null.value_counts().head(5).to_dict(),
            }

        # Alerts
        if completeness < 90:
            alerts.append({
                "column": col, "type": "completeness",
                "severity": "error" if completeness < 50 else "warning",
                "message": f"Completeness at {completeness}% — {null_count} missing values"
            })
        if uniqueness < 10 and unique_count > 1:
            alerts.append({
                "column": col, "type": "low_cardinality",
                "severity": "info",
                "message": f"Low cardinality: only {unique_count} unique values"
            })

        column_reports.append(col_report)

    overall_completeness = round((1 - null_cells / total_cells) * 100, 1) if total_cells > 0 else 0
    overall_score = "good" if overall_completeness >= 95 else "fair" if overall_completeness >= 80 else "poor"

    ranked_columns = sorted(column_reports, key=lambda c: (c["completeness_pct"], -c["unique_count"]))
    healthiest_columns = sorted(column_reports, key=lambda c: (-c["completeness_pct"], c["null_count"]))[:3]
    most_problematic_columns = ranked_columns[:3]

    recommendations = []
    if any(a["type"] == "completeness" for a in alerts):
        recommendations.append("Prioritize missing-value remediation on the least complete columns before downstream modeling.")
    if any(a["type"] == "outliers" for a in alerts):
        recommendations.append("Review numeric outliers to confirm whether they are genuine business events or data entry issues.")
    if total_rows > 0 and df.duplicated().sum() > 0:
        recommendations.append("Deduplicate repeated rows before reporting, or define a business key to isolate intentional repeats.")
    if not recommendations:
        recommendations.append("Dataset quality looks stable; the next step is defining business rules for freshness and acceptable ranges.")

    highlights = {
        "healthiest_columns": [
            {"column": c["column"], "completeness_pct": c["completeness_pct"], "unique_count": c["unique_count"]}
            for c in healthiest_columns
        ],
        "most_problematic_columns": [
            {"column": c["column"], "completeness_pct": c["completeness_pct"], "null_count": c["null_count"]}
            for c in most_problematic_columns
        ],
        "duplicate_rows": int(df.duplicated().sum()),
    }

    return {
        "summary": {
            "filename": filename,
            "total_rows": total_rows,
            "total_columns": total_cols,
            "overall_completeness_pct": overall_completeness,
            "quality_score": overall_score,
            "total_alerts": len(alerts),
            "analyzed_at": datetime.utcnow().isoformat(),
        },
        "columns": column_reports,
        "alerts": alerts,
        "highlights": highlights,
        "recommendations": recommendations,
    }


# ── Endpoints ──────────────────────────────────────────────
@router.post("/check")
async def quality_check(file: UploadFile = File(...)):
    """Upload a CSV/Excel file for automated quality analysis."""
    fn = file.filename or ""
    if not any(fn.lower().endswith(e) for e in (".csv", ".xlsx", ".xls", ".tsv")):
        raise HTTPException(400, "Unsupported file type")
    contents = await file.read()
    try:
        lower = fn.lower()
        if lower.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(contents))
        elif lower.endswith(".tsv"):
            df = pd.read_csv(io.BytesIO(contents), sep="\t")
        else:
            df = pd.read_excel(io.BytesIO(contents))
    except Exception as e:
        raise HTTPException(422, f"Failed to parse file: {str(e)}")

    report = compute_quality_report(df, fn)
    return report


@router.post("/compare")
async def compare_datasets(file1: UploadFile = File(...), file2: UploadFile = File(...)):
    """Compare two datasets for schema drift and distribution changes."""
    def read(f):
        fn = f.filename or ""
        c = f.file.read()
        if fn.lower().endswith(".csv"):
            return pd.read_csv(io.BytesIO(c))
        return pd.read_excel(io.BytesIO(c))

    try:
        df1, df2 = read(file1), read(file2)
    except Exception as e:
        raise HTTPException(422, f"Failed to read files: {str(e)}")

    cols1, cols2 = set(df1.columns), set(df2.columns)
    added = list(cols2 - cols1)
    removed = list(cols1 - cols2)
    common = list(cols1 & cols2)

    drift = []
    for col in common:
        try:
            n1 = pd.to_numeric(df1[col], errors="raise")
            n2 = pd.to_numeric(df2[col], errors="raise")
            mean_change = float(n2.mean() - n1.mean())
            std_change = float(n2.std() - n1.std())
            if abs(mean_change) > n1.std() * 0.5:
                drift.append({"column": col, "type": "mean_shift",
                              "old_mean": round(float(n1.mean()), 2),
                              "new_mean": round(float(n2.mean()), 2),
                              "change": round(mean_change, 2)})
        except (ValueError, TypeError):
            pass

    return {
        "file1": file1.filename, "file2": file2.filename,
        "rows": {"file1": len(df1), "file2": len(df2)},
        "schema_changes": {"added_columns": added, "removed_columns": removed, "common_columns": len(common)},
        "distribution_drift": drift,
    }
