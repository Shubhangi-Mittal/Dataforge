"""
12 — Dataset Audit Report
Unified audit workflow combining schema validation, data quality, EDA, and anomaly checks.
"""

import io
from datetime import datetime

import pandas as pd
from fastapi import APIRouter, UploadFile, File, HTTPException

from app import storage
from app.routers import csv_validator, data_quality, eda_reporter, log_anomaly

router = APIRouter()


def _safe_numeric_scan(df: pd.DataFrame) -> list[dict]:
    scans = []
    for col in df.columns:
        series = pd.to_numeric(df[col], errors="coerce").dropna()
        if len(series) < 5:
            continue
        values = series.astype(float).tolist()
        z_hits = log_anomaly.detect_anomalies_zscore(values, log_anomaly.DETECTION_CONFIG["z_score_threshold"])
        iqr_hits = log_anomaly.detect_anomalies_iqr(values, log_anomaly.DETECTION_CONFIG["iqr_multiplier"])
        total_hits = len(z_hits) + len(iqr_hits)
        if total_hits:
            scans.append({
                "column": col,
                "value_count": len(values),
                "z_score_hits": len(z_hits),
                "iqr_hits": len(iqr_hits),
                "sample_indices": sorted({hit["index"] for hit in z_hits + iqr_hits})[:10],
            })
    return scans


def _build_audit_recommendations(validation: dict, quality: dict, eda: dict, anomaly_scan: list[dict]) -> list[str]:
    recommendations = []
    if validation["summary"]["total_errors"] > 0:
        recommendations.append("Fix schema mismatches and required-field failures before loading this dataset downstream.")
    if quality["summary"]["quality_score"] != "good":
        recommendations.append("Address the lowest-completeness columns first to improve the reliability of analysis and reporting.")
    if anomaly_scan:
        top = anomaly_scan[0]
        recommendations.append(f"Review numeric anomalies in '{top['column']}' before treating the dataset as operationally stable.")
    strong_corrs = eda.get("correlation", {}).get("strong_correlations", [])
    if strong_corrs:
        top_corr = strong_corrs[0]
        recommendations.append(f"Investigate the strong relationship between '{top_corr['col1']}' and '{top_corr['col2']}' for possible business drivers or duplication.")
    if not recommendations:
        recommendations.append("This dataset looks healthy enough to move into downstream modeling or dashboard work.")
    return recommendations


def _build_audit_summary(filename: str, validation: dict, quality: dict, eda: dict, anomaly_scan: list[dict]) -> dict:
    validation_errors = validation["summary"]["total_errors"]
    alerts = quality["summary"]["total_alerts"]
    insight_count = len(eda.get("insights", []))
    anomaly_columns = len(anomaly_scan)

    if validation_errors > 0 or quality["summary"]["quality_score"] == "poor":
        readiness = "needs_attention"
    elif alerts > 0 or anomaly_columns > 0:
        readiness = "review"
    else:
        readiness = "ready"

    return {
        "filename": filename,
        "generated_at": datetime.utcnow().isoformat(),
        "readiness": readiness,
        "validation_errors": validation_errors,
        "quality_alerts": alerts,
        "eda_insights": insight_count,
        "anomaly_columns": anomaly_columns,
        "rows": validation["summary"]["total_rows"],
        "columns": validation["summary"]["total_columns"],
    }


@router.post("/analyze")
async def analyze_dataset(file: UploadFile = File(...)):
    filename = file.filename or ""
    if not any(filename.lower().endswith(e) for e in (".csv", ".xlsx", ".xls", ".tsv")):
        raise HTTPException(400, "Unsupported file type")

    contents = await file.read()
    try:
        validation_report = csv_validator.validate_file(contents, filename, None, max_errors=100)
        df = csv_validator.read_file(contents, filename)
        quality_report = data_quality.compute_quality_report(df.copy(), filename)
        eda_report = eda_reporter.generate_eda(df.copy(), filename)
        anomaly_scan = _safe_numeric_scan(df.copy())
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, f"Dataset audit failed: {exc}")

    recommendations = _build_audit_recommendations(validation_report, quality_report, eda_report, anomaly_scan)
    summary = _build_audit_summary(filename, validation_report, quality_report, eda_report, anomaly_scan)

    audit_report = {
        "summary": summary,
        "recommendations": recommendations,
        "validation_report": validation_report,
        "quality_report": quality_report,
        "eda_report": eda_report,
        "anomaly_scan": anomaly_scan,
    }

    saved = storage.save_report("dataset_audit", f"Dataset Audit — {filename}", audit_report, summary["generated_at"])
    if summary["readiness"] != "ready":
        storage.create_notification(
            {
                "title": "Dataset audit requires review",
                "message": f"{filename} finished with readiness status '{summary['readiness']}'.",
                "level": "warning" if summary["readiness"] == "review" else "error",
                "category": "reports",
                "data": {"report_id": saved["id"], "filename": filename},
            },
            summary["generated_at"],
        )

    audit_report["report_id"] = saved["id"]
    return audit_report


@router.get("/history")
async def audit_history(limit: int = 20):
    reports = storage.list_reports("dataset_audit", limit=limit)
    return {
        "count": len(reports),
        "reports": [
            {
                "id": report["id"],
                "created_at": report["created_at"],
                "name": report["name"],
                "summary": report["data"].get("summary", {}),
            }
            for report in reports
        ],
    }


@router.get("/history/{report_id}")
async def audit_report_detail(report_id: int):
    report = storage.get_report(report_id)
    if not report or report["report_type"] != "dataset_audit":
        raise HTTPException(404, f"Report '{report_id}' not found")
    return report
