"""Bounded web read models: filter, aggregate and page inside SQLite."""

import math
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone

from backend.config import DB_PATH
from backend.parking_metrics import ParkingKpis
from backend.plate_format import normalize_generic_plate_text


def _epoch(value, default_tz=timezone(timedelta(hours=7))):
    try:
        result = datetime.fromisoformat(str(value).strip())
        if result.tzinfo is None:
            result = result.replace(tzinfo=default_tz)
        return result.timestamp()
    except (ValueError, TypeError, OverflowError):
        return None


def _number(value):
    if value is None:
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError, OverflowError):
        return None


def _page(table, where, params, order, limit, offset, columns="*", db_path=None):
    # Identifiers and expressions come only from fixed callers below.
    with closing(sqlite3.connect(db_path or DB_PATH, timeout=10)) as conn:
        conn.row_factory = sqlite3.Row
        conn.create_function("its_epoch", 1, _epoch, deterministic=True)
        conn.create_function(
            "its_utc_epoch", 1, lambda value: _epoch(value, timezone.utc), deterministic=True
        )
        conn.create_function("its_plate", 1, normalize_generic_plate_text, deterministic=True)
        conn.execute("BEGIN")
        condition = " WHERE " + where if where else ""
        total = conn.execute("SELECT count(*) FROM " + table + condition, params).fetchone()[0]
        paging = " LIMIT ? OFFSET ?" if limit is not None or offset else ""
        values = [*params, limit if limit is not None else -1, offset] if paging else params
        rows = conn.execute(
            "SELECT " + columns + " FROM " + table + condition + " ORDER BY " + order + paging,
            values,
        ).fetchall()
    return {
        "items": [dict(row) for row in rows],
        "count": len(rows),
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def logs_page(
    limit=100,
    offset=0,
    status=None,
    ticket_id=None,
    query=None,
    from_time=None,
    to_time=None,
    db_path=None,
):
    where = []
    params = []
    if status:
        where.append("status=?")
        params.append(status)
    if ticket_id:
        where.append("instr(lower(coalesce(ticket_id,'')),lower(?))>0")
        params.append(ticket_id)
    if query:
        where.append(
            "(instr(lower(coalesce(ticket_id,'')),lower(?))>0 OR instr(lower(coalesce(plate_entry,'')),lower(?))>0 OR instr(lower(coalesce(plate_exit,'')),lower(?))>0)"
        )
        params.extend([query] * 3)
    if from_time is not None:
        where.append("its_epoch(entry_time)>=?")
        params.append(from_time.timestamp())
    if to_time is not None:
        where.append("its_epoch(entry_time)<=?")
        params.append(to_time.timestamp())
    return _page(
        "parking_logs",
        " AND ".join(where),
        params,
        "its_epoch(entry_time) DESC,ticket_id DESC",
        limit,
        offset,
        db_path=db_path,
    )


def active_page(limit=None, offset=0, db_path=None, *, query=None, plate=None, status=None):
    where = ["status IN ('IN_PARKING','NEEDS_REVIEW')"]
    params = []
    if status:
        where.append("status=?")
        params.append(status)
    if query:
        normalized = normalize_generic_plate_text(query)
        if normalized:
            where.append("(instr(its_plate(plate_entry),?)>0 OR instr(its_plate(ticket_id),?)>0)")
            params.extend([normalized] * 2)
        else:
            where.append("0")
    if plate is not None:
        where.append("its_plate(plate_entry)=?")
        params.append(normalize_generic_plate_text(plate))
    return _page(
        "parking_logs",
        " AND ".join(where),
        params,
        "its_epoch(entry_time) DESC,ticket_id DESC",
        limit,
        offset,
        "ticket_id,plate_entry,entry_time,status,review_required,review_reason",
        db_path,
    )


def events_page(ticket_id=None, limit=100, offset=0, db_path=None):
    return _explicit_history_times(
        _page(
            "parking_events",
            "ticket_id=?" if ticket_id else "",
            [(ticket_id or "").strip()] if ticket_id else [],
            "its_utc_epoch(created_at) DESC,id DESC",
            limit,
            offset,
            db_path=db_path,
        )
    )


def audit_page(limit=100, offset=0, db_path=None):
    return _explicit_history_times(
        _page(
            "audit_logs",
            "",
            [],
            "its_utc_epoch(created_at) DESC,id DESC",
            limit,
            offset,
            db_path=db_path,
        )
    )


def _explicit_history_times(result):
    # SQLite CURRENT_TIMESTAMP used by old event/audit writers is UTC, unlike old ticket times.
    for row in result["items"]:
        try:
            timestamp = datetime.fromisoformat(str(row.get("created_at")))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            row["created_at"] = timestamp.isoformat()
        except (TypeError, ValueError):
            pass
    return result


def parking_kpis(db_path=None):
    with closing(sqlite3.connect(db_path or DB_PATH, timeout=10)) as conn:
        conn.create_function("its_number", 1, _number, deterministic=True)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(parking_logs)")}
        confidence = [
            f"CASE WHEN typeof({col}) IN ('real','integer') THEN {col} ELSE its_number({col}) END"
            for col in ("entry_ocr_confidence", "exit_ocr_confidence", "ocr_confidence")
            if col in columns
        ]
        summed = "+".join(f"coalesce(sum({col}),0)" for col in confidence) or "0"
        count = "+".join(f"count({col})" for col in confidence) or "0"
        row = conn.execute(
            """SELECT count(*),coalesce(sum(status='IN_PARKING'),0),coalesce(sum(status='COMPLETED'),0),
            coalesce(sum(status='NEEDS_REVIEW'),0),coalesce(sum(status='CANCELLED'),0),coalesce(sum(match_result='MISMATCH'),0),
            coalesce(sum(coalesce(entry_manual_override,0)+coalesce(exit_manual_override,0)>0),0),"""
            + summed
            + ","
            + count
            + " FROM parking_logs"
        ).fetchone()
    total, active, completed, review, cancelled, mismatch, manual, summed, count = row
    return ParkingKpis(
        total,
        active,
        completed,
        review,
        cancelled,
        mismatch,
        manual,
        summed / count if count else 0.0,
        review / total if total else 0.0,
        mismatch / total if total else 0.0,
    )
