"""
09 — Log Anomaly Detector
Ingests log data and detects anomalies using statistical methods
(z-score, IQR, moving averages). Supports streaming simulation.
"""

import json
import random
import math
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter()

# ── In-memory log store + alert history ────────────────────
LOG_STREAMS: dict[str, list] = {}
ALERTS: list[dict] = []
DETECTION_CONFIG = {
    "z_score_threshold": 2.5,
    "iqr_multiplier": 1.5,
    "window_size": 20,
    "min_data_points": 10,
}


class LogEntry(BaseModel):
    stream: str = "default"
    metric: str = "error_rate"
    value: float
    timestamp: Optional[str] = None


class LogBatch(BaseModel):
    stream: str = "default"
    metric: str = "error_rate"
    values: list[float]


def detect_anomalies_zscore(values: list[float], threshold: float = 2.5) -> list[dict]:
    if len(values) < 3:
        return []
    mean = sum(values) / len(values)
    std = (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5
    if std == 0:
        return []
    anomalies = []
    for i, v in enumerate(values):
        z = abs((v - mean) / std)
        if z > threshold:
            anomalies.append({
                "index": i, "value": round(v, 3), "z_score": round(z, 3),
                "method": "z_score", "severity": "critical" if z > 3.5 else "warning",
            })
    return anomalies


def detect_anomalies_iqr(values: list[float], multiplier: float = 1.5) -> list[dict]:
    if len(values) < 4:
        return []
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    q1 = sorted_vals[n // 4]
    q3 = sorted_vals[3 * n // 4]
    iqr = q3 - q1
    lower = q1 - multiplier * iqr
    upper = q3 + multiplier * iqr
    anomalies = []
    for i, v in enumerate(values):
        if v < lower or v > upper:
            anomalies.append({
                "index": i, "value": round(v, 3),
                "bounds": {"lower": round(lower, 3), "upper": round(upper, 3)},
                "method": "iqr", "severity": "warning",
            })
    return anomalies


def detect_anomalies_moving_avg(values: list[float], window: int = 5, threshold: float = 2.0) -> list[dict]:
    if len(values) < window + 1:
        return []
    anomalies = []
    for i in range(window, len(values)):
        window_vals = values[i - window:i]
        mean = sum(window_vals) / len(window_vals)
        std = (sum((v - mean) ** 2 for v in window_vals) / len(window_vals)) ** 0.5
        if std == 0:
            continue
        deviation = abs(values[i] - mean) / std
        if deviation > threshold:
            anomalies.append({
                "index": i, "value": round(values[i], 3),
                "expected": round(mean, 3), "deviation": round(deviation, 3),
                "method": "moving_average", "severity": "warning",
            })
    return anomalies


def generate_sample_data(n: int = 100, anomaly_pct: float = 5) -> list[float]:
    """Generate sample time series with injected anomalies."""
    base = [50 + 10 * math.sin(i * 0.1) + random.gauss(0, 3) for i in range(n)]
    num_anomalies = int(n * anomaly_pct / 100)
    for _ in range(num_anomalies):
        idx = random.randint(0, n - 1)
        base[idx] += random.choice([-1, 1]) * random.uniform(20, 40)
    return [round(v, 2) for v in base]


# ── Endpoints ──────────────────────────────────────────────
@router.post("/ingest")
async def ingest_log(entry: LogEntry):
    """Ingest a single log data point and check for anomalies."""
    stream_key = f"{entry.stream}:{entry.metric}"
    if stream_key not in LOG_STREAMS:
        LOG_STREAMS[stream_key] = []

    ts = entry.timestamp or datetime.utcnow().isoformat()
    LOG_STREAMS[stream_key].append({"value": entry.value, "timestamp": ts})

    # Check for anomalies on recent window
    values = [p["value"] for p in LOG_STREAMS[stream_key][-50:]]
    anomalies = []
    if len(values) >= DETECTION_CONFIG["min_data_points"]:
        anomalies = detect_anomalies_zscore(values, DETECTION_CONFIG["z_score_threshold"])
        # Only alert on the latest point
        latest_anomalies = [a for a in anomalies if a["index"] == len(values) - 1]
        for a in latest_anomalies:
            alert = {"stream": entry.stream, "metric": entry.metric, "timestamp": ts, **a}
            ALERTS.append(alert)

    return {
        "ingested": True,
        "stream": stream_key,
        "data_points": len(LOG_STREAMS[stream_key]),
        "anomaly_detected": len(anomalies) > 0 and any(a["index"] == len(values) - 1 for a in anomalies),
    }


@router.post("/ingest-batch")
async def ingest_batch(batch: LogBatch):
    """Ingest multiple values at once."""
    stream_key = f"{batch.stream}:{batch.metric}"
    if stream_key not in LOG_STREAMS:
        LOG_STREAMS[stream_key] = []

    now = datetime.utcnow()
    for i, v in enumerate(batch.values):
        ts = (now + timedelta(seconds=i)).isoformat()
        LOG_STREAMS[stream_key].append({"value": v, "timestamp": ts})

    return {"ingested": len(batch.values), "stream": stream_key, "total_points": len(LOG_STREAMS[stream_key])}


@router.post("/detect")
async def detect(values: list[float], method: str = Query("all", enum=["z_score", "iqr", "moving_average", "all"])):
    """Run anomaly detection on provided values."""
    results = {"total_values": len(values), "methods": {}}
    if method in ("z_score", "all"):
        results["methods"]["z_score"] = detect_anomalies_zscore(values, DETECTION_CONFIG["z_score_threshold"])
    if method in ("iqr", "all"):
        results["methods"]["iqr"] = detect_anomalies_iqr(values, DETECTION_CONFIG["iqr_multiplier"])
    if method in ("moving_average", "all"):
        results["methods"]["moving_average"] = detect_anomalies_moving_avg(values)

    all_anomalies = []
    for m_name, m_results in results["methods"].items():
        all_anomalies.extend(m_results)
    results["total_anomalies"] = len(all_anomalies)
    return results


@router.get("/generate-sample")
async def get_sample_data(n: int = Query(100, ge=10, le=1000), anomaly_pct: float = Query(5, ge=0, le=30)):
    """Generate sample time series data with injected anomalies for testing."""
    data = generate_sample_data(n, anomaly_pct)
    return {"count": len(data), "anomaly_pct_target": anomaly_pct, "values": data}


@router.get("/streams")
async def list_streams():
    return {"streams": [{"key": k, "data_points": len(v)} for k, v in LOG_STREAMS.items()]}


@router.get("/alerts")
async def get_alerts(limit: int = 20):
    return {"count": len(ALERTS), "alerts": ALERTS[-limit:]}


@router.get("/config")
async def get_config():
    return DETECTION_CONFIG


@router.put("/config")
async def update_config(config: dict):
    DETECTION_CONFIG.update(config)
    return {"message": "Config updated", "config": DETECTION_CONFIG}
