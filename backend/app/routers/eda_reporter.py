"""
05 — Auto EDA Reporter
Generates automated Exploratory Data Analysis reports with
statistics, distributions, correlations, and insights.
"""

import io
import json
from typing import Optional

import pandas as pd
import numpy as np
from fastapi import APIRouter, UploadFile, File, HTTPException

router = APIRouter()


def generate_eda(df: pd.DataFrame, filename: str) -> dict:
    total_rows = len(df)
    total_cols = len(df.columns)
    memory_mb = round(df.memory_usage(deep=True).sum() / 1024 / 1024, 2)

    # Separate numeric and categorical
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    categorical_cols = df.select_dtypes(include=["object", "category"]).columns.tolist()

    # Try to convert string cols to numeric
    for col in categorical_cols[:]:
        try:
            df[col] = pd.to_numeric(df[col], errors="raise")
            numeric_cols.append(col)
            categorical_cols.remove(col)
        except (ValueError, TypeError):
            pass

    # ── Missing values analysis ────────────────────────────
    missing = {}
    for col in df.columns:
        null_count = int(df[col].isnull().sum()) + int((df[col] == "").sum() if df[col].dtype == "object" else 0)
        missing[col] = {"count": null_count, "percentage": round(null_count / total_rows * 100, 1) if total_rows > 0 else 0}

    # ── Numeric column analysis ────────────────────────────
    numeric_analysis = {}
    for col in numeric_cols:
        series = df[col].dropna()
        if len(series) == 0:
            continue
        stats = {
            "count": int(len(series)),
            "mean": round(float(series.mean()), 3),
            "median": round(float(series.median()), 3),
            "std": round(float(series.std()), 3),
            "min": round(float(series.min()), 3),
            "max": round(float(series.max()), 3),
            "q25": round(float(series.quantile(0.25)), 3),
            "q75": round(float(series.quantile(0.75)), 3),
            "skewness": round(float(series.skew()), 3),
            "kurtosis": round(float(series.kurtosis()), 3),
            "zeros_count": int((series == 0).sum()),
            "negative_count": int((series < 0).sum()),
        }
        # Distribution (10 bins)
        try:
            hist_values, bin_edges = np.histogram(series, bins=10)
            stats["histogram"] = {
                "counts": hist_values.tolist(),
                "bin_edges": [round(float(b), 3) for b in bin_edges.tolist()],
            }
        except Exception:
            pass

        # Outlier detection (IQR)
        q1, q3 = series.quantile(0.25), series.quantile(0.75)
        iqr = q3 - q1
        lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        outliers = series[(series < lower) | (series > upper)]
        stats["outliers"] = {"count": int(len(outliers)), "lower_bound": round(float(lower), 3), "upper_bound": round(float(upper), 3)}

        numeric_analysis[col] = stats

    # ── Categorical column analysis ────────────────────────
    categorical_analysis = {}
    for col in categorical_cols:
        series = df[col].dropna()
        if len(series) == 0:
            continue
        vc = series.value_counts()
        categorical_analysis[col] = {
            "unique_count": int(series.nunique()),
            "top_values": {str(k): int(v) for k, v in vc.head(10).items()},
            "mode": str(vc.index[0]) if len(vc) > 0 else None,
            "mode_frequency": int(vc.iloc[0]) if len(vc) > 0 else 0,
            "avg_length": round(float(series.astype(str).str.len().mean()), 1),
        }

    # ── Correlation matrix (numeric only) ──────────────────
    correlation = {}
    if len(numeric_cols) >= 2:
        corr_df = df[numeric_cols].corr()
        # Find strong correlations
        strong_corrs = []
        for i in range(len(numeric_cols)):
            for j in range(i + 1, len(numeric_cols)):
                val = float(corr_df.iloc[i, j])
                if abs(val) > 0.5:
                    strong_corrs.append({
                        "col1": numeric_cols[i],
                        "col2": numeric_cols[j],
                        "correlation": round(val, 3),
                        "strength": "strong" if abs(val) > 0.7 else "moderate",
                    })
        correlation = {
            "matrix": {c: {c2: round(float(corr_df.loc[c, c2]), 3) for c2 in numeric_cols} for c in numeric_cols},
            "strong_correlations": sorted(strong_corrs, key=lambda x: abs(x["correlation"]), reverse=True),
        }

    # ── Auto insights ──────────────────────────────────────
    insights = []
    for col, m in missing.items():
        if m["percentage"] > 20:
            insights.append({"type": "warning", "message": f"'{col}' has {m['percentage']}% missing values"})
    for col, stats in numeric_analysis.items():
        if stats.get("outliers", {}).get("count", 0) > total_rows * 0.05:
            insights.append({"type": "warning", "message": f"'{col}' has significant outliers ({stats['outliers']['count']} rows)"})
        if abs(stats.get("skewness", 0)) > 2:
            direction = "right" if stats["skewness"] > 0 else "left"
            insights.append({"type": "info", "message": f"'{col}' is heavily {direction}-skewed (skewness={stats['skewness']})"})
    for c in correlation.get("strong_correlations", [])[:3]:
        insights.append({"type": "info", "message": f"Strong correlation ({c['correlation']}) between '{c['col1']}' and '{c['col2']}'"})
    if total_rows < 100:
        insights.append({"type": "warning", "message": f"Small dataset ({total_rows} rows) — statistical measures may not be reliable"})

    # ── Duplicate analysis ─────────────────────────────────
    dup_count = int(df.duplicated().sum())

    return {
        "overview": {
            "filename": filename,
            "total_rows": total_rows,
            "total_columns": total_cols,
            "numeric_columns": len(numeric_cols),
            "categorical_columns": len(categorical_cols),
            "memory_mb": memory_mb,
            "duplicate_rows": dup_count,
            "duplicate_pct": round(dup_count / total_rows * 100, 1) if total_rows > 0 else 0,
        },
        "missing_values": missing,
        "numeric_analysis": numeric_analysis,
        "categorical_analysis": categorical_analysis,
        "correlation": correlation,
        "insights": insights,
    }


# ── Endpoints ──────────────────────────────────────────────
@router.post("/analyze")
async def analyze_dataset(file: UploadFile = File(...)):
    """Upload a CSV/Excel for full EDA report."""
    fn = file.filename or ""
    if not any(fn.lower().endswith(e) for e in (".csv", ".xlsx", ".xls", ".tsv")):
        raise HTTPException(400, "Unsupported file type")
    contents = await file.read()
    try:
        if fn.lower().endswith(".csv"):
            df = pd.read_csv(io.BytesIO(contents))
        elif fn.lower().endswith(".tsv"):
            df = pd.read_csv(io.BytesIO(contents), sep="\t")
        else:
            df = pd.read_excel(io.BytesIO(contents))
    except Exception as e:
        raise HTTPException(422, f"Parse error: {str(e)}")

    return generate_eda(df, fn)


@router.post("/quick-stats")
async def quick_stats(file: UploadFile = File(...)):
    """Quick summary stats only."""
    fn = file.filename or ""
    contents = await file.read()
    try:
        if fn.lower().endswith(".csv"):
            df = pd.read_csv(io.BytesIO(contents))
        else:
            df = pd.read_excel(io.BytesIO(contents))
    except Exception as e:
        raise HTTPException(422, f"Parse error: {str(e)}")

    return {
        "filename": fn,
        "rows": len(df),
        "columns": len(df.columns),
        "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
        "head": df.head(5).to_dict(orient="records"),
        "describe": json.loads(df.describe(include="all").to_json()),
    }
