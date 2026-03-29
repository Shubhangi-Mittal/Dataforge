"""
01 — CSV Schema Validator
Validates CSV/Excel files against user-defined or auto-inferred schemas.
"""

import io
import json
import re
import csv
from datetime import datetime
from typing import Any, Optional

import math

import numpy as np
import pandas as pd
from fastapi import APIRouter, UploadFile, File, HTTPException, Query
from fastapi.responses import JSONResponse


def _sanitize(obj):
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


class _NumpySafeResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        def default(obj):
            if isinstance(obj, (np.bool_,)):
                return bool(obj)
            if isinstance(obj, (np.integer,)):
                return int(obj)
            if isinstance(obj, (np.floating,)):
                v = float(obj)
                return None if (math.isnan(v) or math.isinf(v)) else v
            if isinstance(obj, np.ndarray):
                return _sanitize(obj.tolist())
            raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")
        return json.dumps(_sanitize(content), default=default).encode("utf-8")

router = APIRouter()

# ── In-memory schema store ─────────────────────────────────
SCHEMAS: dict[str, dict] = {}

VALID_TYPES = {"string", "integer", "float", "boolean", "date", "email"}


def read_file(file_bytes: bytes, filename: str) -> pd.DataFrame:
    lower = filename.lower()
    # Excel formats first
    if lower.endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(file_bytes), dtype=str, keep_default_na=False)

    text = None
    # TSV explicit
    if lower.endswith(".tsv"):
        try:
            return pd.read_csv(io.BytesIO(file_bytes), sep="\t", dtype=str, keep_default_na=False)
        except Exception:
            # fall through to more robust parsing
            pass

    # Quick content sniffing: reject obvious non-CSV text formats (RTF, PDF, HTML)
    try:
        sample_text = file_bytes.decode("utf-8", errors="ignore").lstrip()
        low = sample_text.lower()
        if low.startswith('{\\rtf') or low.startswith('%pdf') or low.startswith('<!doctype') or low.startswith('<html') or low.startswith('<?xml'):
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="Uploaded file doesn't appear to be CSV/TSV/Excel (detected RTF/PDF/HTML). Please upload a valid CSV or Excel file.")
    except Exception:
        # decoding sniff failed; continue to parsing attempts
        pass

    # Binary check: if file contains many null bytes it's probably not a text CSV
    try:
        nulls = file_bytes.count(b"\x00")
        if nulls and (nulls / max(1, len(file_bytes))) > 0.01:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="Uploaded file appears to be binary or unsupported format. Please upload a CSV or Excel file.")
    except Exception:
        pass

    # Try default fast parser first, then fallback strategies on ParserError
    try:
        return pd.read_csv(io.BytesIO(file_bytes), dtype=str, keep_default_na=False)
    except pd.errors.ParserError:
        # decode to text for sniffing/fallbacks using several encodings
        text = None
        for enc in ("utf-8", "utf-16", "latin-1"):
            try:
                text = file_bytes.decode(enc)
                break
            except Exception:
                continue
        if text is None:
            text = file_bytes.decode("utf-8", errors="replace")

        # Try sniffing delimiter from the content
        try:
            sample = "\n".join(text.splitlines()[:50]) or text
            dialect = csv.Sniffer().sniff(sample)
            delim = dialect.delimiter
            return pd.read_csv(io.StringIO(text), sep=delim, dtype=str, keep_default_na=False, engine="python")
        except Exception:
            # Try common delimiters with the slower python engine and robust options
            for sep in [",", "\t", ";", "|"]:
                try:
                    df = pd.read_csv(io.StringIO(text), sep=sep, dtype=str, keep_default_na=False, engine="python", quoting=csv.QUOTE_MINIMAL)
                    # Basic sanity: require at least 1 column and more than 0 rows
                    if df.shape[0] >= 0 and df.shape[1] >= 1:
                        return df
                except Exception:
                    continue
        # As a last resort, read as a single-column CSV (preserve data) but treat this as potentially malformed
        try:
            df = pd.read_csv(io.StringIO(text), header=None, dtype=str, keep_default_na=False, engine="python")
            return df
        except Exception:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="Could not parse uploaded CSV. Please ensure the file is a valid CSV or Excel spreadsheet.")

    except Exception:
        raise ValueError(f"Unsupported format or failed to parse: {filename}")


def infer_schema(df: pd.DataFrame) -> dict:
    columns = {}
    for col in df.columns:
        col_data = df[col].replace("", pd.NA).dropna()
        if len(col_data) == 0:
            columns[col] = {"type": "string", "required": False, "inferred": True}
            continue
        try:
            col_data.astype(int)
            columns[col] = {"type": "integer", "required": df[col].replace("", pd.NA).notna().all(), "inferred": True}
            continue
        except (ValueError, TypeError):
            pass
        try:
            col_data.astype(float)
            columns[col] = {"type": "float", "required": df[col].replace("", pd.NA).notna().all(), "inferred": True}
            continue
        except (ValueError, TypeError):
            pass
        bool_vals = {"true", "false", "1", "0", "yes", "no", "t", "f", "y", "n"}
        if col_data.str.lower().isin(bool_vals).all():
            columns[col] = {"type": "boolean", "required": df[col].replace("", pd.NA).notna().all(), "inferred": True}
            continue
        try:
            pd.to_datetime(col_data, format="%Y-%m-%d")
            columns[col] = {"type": "date", "required": df[col].replace("", pd.NA).notna().all(), "date_format": "%Y-%m-%d", "inferred": True}
            continue
        except (ValueError, TypeError):
            pass
        email_pat = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if col_data.str.match(email_pat).all():
            columns[col] = {"type": "email", "required": df[col].replace("", pd.NA).notna().all(), "inferred": True}
            continue
        columns[col] = {"type": "string", "required": df[col].replace("", pd.NA).notna().all(), "inferred": True}
    return {"name": "_auto_inferred", "description": "Auto-inferred schema", "columns": columns}


def validate_cell(value: str, expected_type: str, col_def: dict) -> list[str]:
    errors = []
    if expected_type == "integer":
        try:
            int(value)
        except ValueError:
            return [f"Expected integer, got '{value}'"]
    elif expected_type == "float":
        try:
            float(value)
        except ValueError:
            return [f"Expected float, got '{value}'"]
    elif expected_type == "boolean":
        if value.lower() not in {"true", "false", "1", "0", "yes", "no", "t", "f", "y", "n"}:
            return [f"Expected boolean, got '{value}'"]
    elif expected_type == "date":
        fmt = col_def.get("date_format", "%Y-%m-%d")
        try:
            datetime.strptime(value, fmt)
        except ValueError:
            return [f"Expected date '{fmt}', got '{value}'"]
    elif expected_type == "email":
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', value):
            return [f"Invalid email: '{value}'"]

    # Constraints
    if expected_type == "string":
        ml = col_def.get("min_length")
        xl = col_def.get("max_length")
        if ml is not None and len(value) < ml:
            errors.append(f"Length {len(value)} below min {ml}")
        if xl is not None and len(value) > xl:
            errors.append(f"Length {len(value)} exceeds max {xl}")
    if expected_type in ("integer", "float"):
        try:
            n = float(value)
            mv = col_def.get("min_value")
            xv = col_def.get("max_value")
            if mv is not None and n < mv:
                errors.append(f"Value {n} below min {mv}")
            if xv is not None and n > xv:
                errors.append(f"Value {n} exceeds max {xv}")
        except ValueError:
            pass
    allowed = col_def.get("allowed_values")
    if allowed and value not in allowed:
        errors.append(f"'{value}' not in {allowed}")
    pattern = col_def.get("pattern")
    if pattern and not re.match(pattern, value):
        errors.append(f"'{value}' doesn't match pattern '{pattern}'")
    return errors


def validate_file(file_bytes: bytes, filename: str, schema: Optional[dict], max_errors: int = 100) -> dict:
    df = read_file(file_bytes, filename)
    return validate_dataframe(df, filename, schema, max_errors=max_errors)


def validate_dataframe(df: pd.DataFrame, filename: str, schema: Optional[dict], max_errors: int = 100) -> dict:
    total_rows, total_cols = len(df), len(df.columns)
    inferred = schema is None
    if inferred:
        schema = infer_schema(df)
    schema_cols = schema.get("columns", {})
    errors, rows_with_errors = [], set()
    col_stats = {c: {"valid": 0, "invalid": 0, "null": 0} for c in schema_cols}

    missing = set(schema_cols.keys()) - set(df.columns.str.strip())
    extra = set(df.columns.str.strip()) - set(schema_cols.keys())
    for col in missing:
        if schema_cols[col].get("required"):
            errors.append({"row": 0, "column": col, "error_type": "missing_column",
                           "message": f"Required column '{col}' missing", "value": None, "severity": "critical"})

    for row_idx, row in df.iterrows():
        if len(errors) >= max_errors:
            break
        row_num = int(row_idx) + 2
        for col_name, col_def in schema_cols.items():
            if col_name not in df.columns or len(errors) >= max_errors:
                continue
            raw = str(row.get(col_name, "")).strip()
            is_empty = raw == "" or raw.lower() == "nan"
            etype = col_def.get("type", "string")
            if is_empty:
                col_stats[col_name]["null"] += 1
                if col_def.get("required"):
                    errors.append({"row": row_num, "column": col_name, "error_type": "null_value",
                                   "message": f"Required '{col_name}' is empty", "value": None, "severity": "error"})
                    rows_with_errors.add(row_num)
                continue
            cell_errors = validate_cell(raw, etype, col_def)
            if cell_errors:
                col_stats[col_name]["invalid"] += 1
                for e in cell_errors[:3]:
                    errors.append({"row": row_num, "column": col_name, "error_type": "validation_error",
                                   "message": e, "value": raw, "severity": "error"})
                rows_with_errors.add(row_num)
            else:
                col_stats[col_name]["valid"] += 1

    for col_name, col_def in schema_cols.items():
        if col_def.get("unique") and col_name in df.columns:
            dupes = df[df[col_name].duplicated(keep=False)]
            for dv in dupes[col_name].unique()[:5]:
                if len(errors) >= max_errors:
                    break
                dupe_rows = df[df[col_name] == dv].index.tolist()
                errors.append({"row": [r + 2 for r in dupe_rows], "column": col_name,
                               "error_type": "uniqueness_violation",
                               "message": f"Duplicate '{dv}' in {len(dupe_rows)} rows",
                               "value": str(dv), "severity": "error"})

    is_valid = len(errors) == 0
    report = {
        "summary": {
            "is_valid": is_valid,
            "status": "PASS" if is_valid else "FAIL",
            "filename": filename,
            "schema_used": schema.get("name", "unknown"),
            "total_rows": total_rows,
            "total_columns": total_cols,
            "total_errors": len(errors),
            "rows_with_errors": len(rows_with_errors),
            "error_rate": f"{(len(rows_with_errors) / total_rows * 100):.1f}%" if total_rows > 0 else "0%",
            "missing_columns": list(missing),
            "extra_columns": list(extra),
        },
        "column_report": {c: {"valid": s["valid"], "invalid": s["invalid"], "null": s["null"],
                               "validity_pct": f"{(s['valid'] / total_rows * 100):.1f}%" if total_rows > 0 else "0%"}
                          for c, s in col_stats.items()},
        "errors": errors,
        "schema": schema,
    }
    if inferred:
        report["inferred_schema"] = schema
    return report


# ── Endpoints ──────────────────────────────────────────────
@router.get("/schemas")
async def list_schemas():
    return {"count": len(SCHEMAS), "schemas": [{"name": s["name"], "description": s.get("description", ""),
            "columns": len(s.get("columns", {}))} for s in SCHEMAS.values()]}


@router.get("/schemas/{name}")
async def get_schema(name: str):
    if name not in SCHEMAS:
        raise HTTPException(404, f"Schema '{name}' not found")
    return SCHEMAS[name]


@router.post("/schemas")
async def create_schema(schema: dict):
    name = schema.get("name", "").strip()
    if not name or not schema.get("columns"):
        raise HTTPException(400, "Schema needs 'name' and 'columns'")
    for cn, cd in schema["columns"].items():
        if cd.get("type", "string") not in VALID_TYPES:
            raise HTTPException(400, f"Invalid type for '{cn}'")
    SCHEMAS[name] = schema
    return {"message": f"Schema '{name}' created", "schema": schema}


@router.delete("/schemas/{name}")
async def delete_schema(name: str):
    if name not in SCHEMAS:
        raise HTTPException(404, f"Schema '{name}' not found")
    del SCHEMAS[name]
    return {"message": f"Deleted '{name}'"}


@router.post("/validate/{schema_name}")
async def validate(schema_name: str, file: UploadFile = File(...),
                   max_errors: int = Query(100, ge=1, le=10000)):
    schema = SCHEMAS.get(schema_name)
    if not schema:
        raise HTTPException(404, f"Schema '{schema_name}' not found")
    fn = file.filename or ""
    if not any(fn.lower().endswith(e) for e in (".csv", ".xlsx", ".xls", ".tsv")):
        raise HTTPException(400, "Unsupported file type")
    contents = await file.read()
    report = validate_file(contents, fn, schema, max_errors)
    return _NumpySafeResponse(report, status_code=200 if report["summary"]["is_valid"] else 422)


@router.post("/validate-auto")
async def validate_auto(file: UploadFile = File(...), max_errors: int = Query(100)):
    fn = file.filename or ""
    if not any(fn.lower().endswith(e) for e in (".csv", ".xlsx", ".xls", ".tsv")):
        raise HTTPException(400, "Unsupported file type")
    contents = await file.read()
    report = validate_file(contents, fn, None, max_errors)
    return _NumpySafeResponse(report, status_code=200 if report["summary"]["is_valid"] else 422)
