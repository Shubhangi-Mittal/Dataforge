"""
06 — Lakehouse Organizer
Simulates S3 lakehouse file management: partitioning by date/source,
format conversion tracking, and metadata cataloging.
"""

import json
import os
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

router = APIRouter()

# ── In-memory catalog ─────────────────────────────────────
CATALOG: dict[str, dict] = {}
PARTITIONS: dict[str, list] = {}
INGEST_LOG: list[dict] = []


class FileEntry(BaseModel):
    filename: str
    source: str = "unknown"
    size_bytes: int = 0
    format: str = "csv"


def generate_partition_path(source: str, dt: Optional[datetime] = None) -> str:
    dt = dt or datetime.utcnow()
    return f"lakehouse/{source}/year={dt.year}/month={dt.month:02d}/day={dt.day:02d}"


def catalog_file(filename: str, source: str, size: int, fmt: str) -> dict:
    now = datetime.utcnow()
    partition_path = generate_partition_path(source, now)
    target_name = filename.rsplit(".", 1)[0] + ".parquet" if fmt != "parquet" else filename

    entry = {
        "original_filename": filename,
        "target_filename": target_name,
        "source": source,
        "partition_path": partition_path,
        "full_path": f"{partition_path}/{target_name}",
        "original_format": fmt,
        "target_format": "parquet",
        "size_bytes": size,
        "converted": fmt != "parquet",
        "cataloged_at": now.isoformat(),
        "metadata": {
            "ingestion_timestamp": now.isoformat(),
            "source_system": source,
            "partition_keys": {
                "year": now.year,
                "month": now.month,
                "day": now.day,
            },
        },
    }

    CATALOG[entry["full_path"]] = entry

    if partition_path not in PARTITIONS:
        PARTITIONS[partition_path] = []
    PARTITIONS[partition_path].append(entry["full_path"])

    INGEST_LOG.append({
        "action": "ingest",
        "file": entry["full_path"],
        "source": source,
        "timestamp": now.isoformat(),
        "size_bytes": size,
        "converted_to_parquet": entry["converted"],
    })

    return entry


# ── Endpoints ──────────────────────────────────────────────
@router.post("/ingest")
async def ingest_file(file: UploadFile = File(...), source: str = "uploads"):
    """Simulate ingesting a file into the lakehouse."""
    fn = file.filename or "unknown.csv"
    contents = await file.read()
    fmt = fn.rsplit(".", 1)[-1].lower() if "." in fn else "csv"
    entry = catalog_file(fn, source, len(contents), fmt)
    return {"message": "File ingested and cataloged", "entry": entry}


@router.post("/ingest-metadata")
async def ingest_metadata(entry: FileEntry):
    """Catalog a file without uploading (metadata only)."""
    result = catalog_file(entry.filename, entry.source, entry.size_bytes, entry.format)
    return {"message": "Metadata cataloged", "entry": result}


@router.get("/catalog")
async def list_catalog(source: Optional[str] = None):
    """List all cataloged files, optionally filtered by source."""
    entries = list(CATALOG.values())
    if source:
        entries = [e for e in entries if e["source"] == source]
    return {"count": len(entries), "files": entries}


@router.get("/partitions")
async def list_partitions():
    """List all partition paths and file counts."""
    return {
        "count": len(PARTITIONS),
        "partitions": [
            {"path": p, "file_count": len(files), "files": files}
            for p, files in sorted(PARTITIONS.items())
        ],
    }


@router.get("/log")
async def ingestion_log(limit: int = 20):
    """View recent ingestion activity."""
    return {"count": len(INGEST_LOG), "log": INGEST_LOG[-limit:]}


@router.get("/stats")
async def lakehouse_stats():
    """Overall lakehouse statistics."""
    total_files = len(CATALOG)
    total_size = sum(e["size_bytes"] for e in CATALOG.values())
    sources = list(set(e["source"] for e in CATALOG.values()))
    formats = {}
    for e in CATALOG.values():
        fmt = e["original_format"]
        formats[fmt] = formats.get(fmt, 0) + 1
    return {
        "total_files": total_files,
        "total_size_bytes": total_size,
        "total_size_mb": round(total_size / 1024 / 1024, 2),
        "unique_sources": sources,
        "total_partitions": len(PARTITIONS),
        "format_breakdown": formats,
        "conversion_rate": f"{sum(1 for e in CATALOG.values() if e['converted']) / total_files * 100:.0f}%" if total_files > 0 else "0%",
    }
