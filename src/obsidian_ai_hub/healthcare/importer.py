"""Apple Health export importer — streaming iterparse, fingerprint, batch commit.

Covers Phase 2 (Record/Workout/ActivitySummary) + Phase 3 ECG file-reference.
All raw types are persisted; ECG samples remain file-referenced.
No exception masking: unexpected failures propagate after marking import as failed.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from xml.etree.ElementTree import iterparse

from obsidian_ai_hub.healthcare.store import (
    create_import_row,
    finish_import_row,
    get_healthcare_db_connection,
)

logger = logging.getLogger(__name__)

# Keep small for tests; production caller may pass larger batch_size
DEFAULT_BATCH_SIZE = 5000


def _fingerprint_record(
    *,
    type_: str,
    source_name: str,
    source_version: str | None,
    start_date: str,
    end_date: str,
    value: str | None,
    unit: str | None,
    sync_id: str | None,
) -> str:
    if sync_id:
        raw = f"{type_}|{sync_id}"
    else:
        raw = (
            f"{type_}|{source_name}|{source_version or ''}|{start_date}|{end_date}"
            f"|{value or ''}|{unit or ''}"
        )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _fingerprint_workout(
    *,
    activity_type: str,
    source_name: str,
    source_version: str | None,
    start_date: str,
    end_date: str,
) -> str:
    raw = f"{activity_type}|{source_name}|{source_version or ''}|{start_date}|{end_date}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _parse_float(val: str | None) -> float | None:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except ValueError:
        return None


def _parse_ecg_csv_header(csv_path: Path) -> dict:
    """Parse Japanese ECG CSV header into health_ecg fields.

    Returns dict with recorded_at, classification, symptoms, software_version,
    device, sample_rate_hz, lead, unit. Missing fields are None.
    """
    # Use csv module to handle quoted fields correctly
    text = csv_path.read_text(encoding="utf-8-sig", errors="replace")
    # The header is the first ~15 lines before samples; parse line-by-line with csv
    fields: dict[str, str | None] = {}
    for raw_line in text.splitlines():
        if not raw_line.strip():
            continue
        # Stop at samples: a line that is a single float with no comma
        stripped = raw_line.strip().strip('"').strip("'")
        if "," not in raw_line:
            # Could be sample line; check if numeric
            try:
                float(stripped)
                # First sample encountered -> header done
                break
            except ValueError:
                pass
        # Parse as CSV row with 2 columns (key,value)
        try:
            row = next(csv.reader([raw_line]))
        except Exception:
            continue
        if len(row) < 2:
            continue
        key = row[0].strip()
        val = row[1].strip() if len(row) > 1 else ""
        # Join remaining columns if any (should not happen for header)
        if len(row) > 2:
            val = ",".join(row[1:]).strip()
        val = val.strip('"').strip("'")
        if key == "記録日":
            fields["recorded_at"] = val or None
        elif key == "分類":
            fields["classification"] = val or None
        elif key == "症状":
            fields["symptoms"] = val or None
        elif key == "ソフトウェアバージョン":
            fields["software_version"] = val or None
        elif key == "デバイス":
            fields["device"] = val or None
        elif key == "サンプルレート":
            # e.g. "512ヘルツ"
            num = "".join(ch for ch in val if ch.isdigit())
            fields["sample_rate_hz"] = int(num) if num else None
        elif key == "リード":
            fields["lead"] = val or None
        elif key == "単位":
            fields["unit"] = val or None
    return {
        "recorded_at": fields.get("recorded_at"),
        "classification": fields.get("classification"),
        "symptoms": fields.get("symptoms"),
        "software_version": fields.get("software_version"),
        "device": fields.get("device"),
        "sample_rate_hz": fields.get("sample_rate_hz"),
        "lead": fields.get("lead"),
        "unit": fields.get("unit"),
    }


def import_export(
    export_dir: Path | str,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    dry_run: bool = False,
    conn: sqlite3.Connection | None = None,
) -> dict:
    """Import an Apple Health export directory into healthcare.sqlite3.

    export_dir must contain export.xml and optionally electrocardiograms/*.csv.
    Returns stats dict. When dry_run=True, no DB writes are performed — the
    XML is still parsed and stats are returned.
    """
    export_dir = Path(export_dir).expanduser()
    export_xml = export_dir / "export.xml"
    if not export_dir.is_dir():
        raise FileNotFoundError(f"Export dir not found: {export_dir}")
    if not export_xml.is_file():
        raise FileNotFoundError(f"export.xml not found in {export_dir}")

    started_at = datetime.now().isoformat()
    import_id = f"himp_{uuid.uuid4().hex}"

    # Early dry_run path: just count without touching DB
    if dry_run:
        return _dry_run_count(export_xml, export_dir)

    close_conn = False
    if conn is None:
        conn = get_healthcare_db_connection()
        close_conn = True

    try:
        # Create import row
        # We need locale/export_date/me_json early; parse them in a first pass
        # but for efficiency we do it in the same streaming pass and update the row later.
        # Start with minimal row, then update after parsing header.
        create_import_row(
            conn,
            import_id=import_id,
            export_dir=str(export_dir),
            started_at=started_at,
        )
        conn.commit()

        stats = _stream_import(
            export_xml=export_xml,
            export_dir=export_dir,
            import_id=import_id,
            conn=conn,
            batch_size=batch_size,
        )

        # Update header fields if captured
        header = stats.pop("_header", {})
        if header:
            conn.execute(
                """
                UPDATE health_imports
                SET export_date = COALESCE(?, export_date),
                    locale = COALESCE(?, locale),
                    me_json = COALESCE(?, me_json),
                    hk_export_version = COALESCE(?, hk_export_version)
                WHERE import_id = ?
                """,
                (
                    header.get("export_date"),
                    header.get("locale"),
                    header.get("me_json"),
                    header.get("hk_export_version"),
                    import_id,
                ),
            )

        finished_at = datetime.now().isoformat()
        # Ensure cda_skipped flag per plan
        stats["cda_skipped"] = True
        finish_import_row(
            conn,
            import_id=import_id,
            finished_at=finished_at,
            status="succeeded",
            stats=stats,
        )
        conn.commit()
        logger.info("Healthcare import %s succeeded: %s", import_id, stats)
        return {"import_id": import_id, **stats}

    except Exception as exc:
        # Mark as failed, then propagate (no masking)
        try:
            finished_at = datetime.now().isoformat()
            finish_import_row(
                conn,
                import_id=import_id,
                finished_at=finished_at,
                status="failed",
                stats={},
                error=f"{type(exc).__name__}: {exc}",
            )
            conn.commit()
        except Exception:
            # If even the failure marking fails, let original exception propagate
            pass
        raise
    finally:
        if close_conn:
            conn.close()


def _dry_run_count(export_xml: Path, export_dir: Path) -> dict:
    counts = {"records": 0, "workouts": 0, "activity_summaries": 0, "ecg_files": 0}
    # Count ECG files without DB
    ecg_dir = export_dir / "electrocardiograms"
    if ecg_dir.is_dir():
        counts["ecg_files"] = len(list(ecg_dir.glob("*.csv")))
    # Count XML elements streaming
    context = iterparse(str(export_xml), events=("end",))
    for event, elem in context:
        if elem.tag == "Record":
            counts["records"] += 1
            elem.clear()
        elif elem.tag == "Workout":
            counts["workouts"] += 1
            elem.clear()
        elif elem.tag == "ActivitySummary":
            counts["activity_summaries"] += 1
            elem.clear()
    counts["cda_skipped"] = True
    counts["dry_run"] = True
    return counts


def _stream_import(
    *,
    export_xml: Path,
    export_dir: Path,
    import_id: str,
    conn: sqlite3.Connection,
    batch_size: int,
) -> dict:
    counts = {
        "records": 0,
        "workouts": 0,
        "activity_summaries": 0,
        "ecg_files": 0,
        "ignored_duplicates": 0,
        "metadata_entries": 0,
        "hrv_beats": 0,
    }
    header: dict[str, str | None] = {
        "export_date": None,
        "locale": None,
        "me_json": None,
        "hk_export_version": "14",
    }

    # For batch commit tracking
    pending_commits = 0

    context = iterparse(str(export_xml), events=("start", "end"))
    for event, elem in context:
        if event == "start" and elem.tag == "HealthData":
            header["locale"] = elem.get("locale")
        elif event == "end":
            if elem.tag == "ExportDate":
                header["export_date"] = elem.get("value")
                elem.clear()
            elif elem.tag == "Me":
                # Capture all Me attributes as JSON (contains DOB etc. — not logged)
                header["me_json"] = json.dumps(dict(elem.attrib), ensure_ascii=False)
                elem.clear()
            elif elem.tag == "Record":
                inserted, meta_cnt, hrv_cnt = _handle_record(elem, import_id, conn)
                counts["records"] += 1
                if inserted:
                    counts["metadata_entries"] += meta_cnt
                    counts["hrv_beats"] += hrv_cnt
                else:
                    counts["ignored_duplicates"] += 1
                pending_commits += 1
                elem.clear()
            elif elem.tag == "Workout":
                inserted = _handle_workout(elem, import_id, conn)
                counts["workouts"] += 1
                if not inserted:
                    counts["ignored_duplicates"] += 1
                pending_commits += 1
                elem.clear()
            elif elem.tag == "ActivitySummary":
                inserted = _handle_activity_summary(elem, import_id, conn)
                counts["activity_summaries"] += 1
                if not inserted:
                    counts["ignored_duplicates"] += 1
                pending_commits += 1
                elem.clear()
            elif elem.tag == "HealthData":
                elem.clear()

            if pending_commits >= batch_size:
                conn.commit()
                pending_commits = 0
                if (counts["records"] + counts["workouts"]) % 10000 == 0:
                    logger.info(
                        "Import progress: records=%s workouts=%s",
                        counts["records"],
                        counts["workouts"],
                    )

    if pending_commits:
        conn.commit()

    # ECG files after XML
    ecg_counts = _handle_ecg_files(export_dir, import_id, conn)
    counts["ecg_files"] = ecg_counts

    # Attach header for caller to update health_imports
    counts["_header"] = header  # type: ignore[assignment]
    return counts


def _handle_record(elem, import_id: str, conn: sqlite3.Connection) -> tuple[bool, int, int]:
    """Insert a Record element. Returns (inserted, metadata_count, hrv_count)."""
    attrib = elem.attrib
    type_ = attrib.get("type")
    if not type_:
        return (False, 0, 0)
    source_name = attrib.get("sourceName", "")
    source_version = attrib.get("sourceVersion")
    unit = attrib.get("unit")
    value = attrib.get("value")
    device_raw = attrib.get("device")
    creation_date = attrib.get("creationDate")
    start_date = attrib.get("startDate", "")
    end_date = attrib.get("endDate", "")

    # Collect metadata and HRV beats before fingerprint (need syncId)
    metadata: list[tuple[str, str]] = []
    hrv_beats: list[tuple[float, str]] = []
    sync_id: str | None = None

    for child in elem:
        if child.tag == "MetadataEntry":
            k = child.get("key", "")
            v = child.get("value", "")
            if k and v is not None:
                metadata.append((k, v))
                if k == "HKMetadataKeySyncIdentifier":
                    sync_id = v
        elif child.tag == "HeartRateVariabilityMetadataList":
            seq = 0
            for bpm_elem in child:
                if bpm_elem.tag == "InstantaneousBeatsPerMinute":
                    bpm = _parse_float(bpm_elem.get("bpm"))
                    t = bpm_elem.get("time", "")
                    if bpm is not None:
                        hrv_beats.append((bpm, t))
                        seq += 1

    fingerprint = _fingerprint_record(
        type_=type_,
        source_name=source_name,
        source_version=source_version,
        start_date=start_date,
        end_date=end_date,
        value=value,
        unit=unit,
        sync_id=sync_id,
    )

    # Determine numeric vs text
    value_text: str | None = value
    value_numeric: float | None = None
    if unit is not None and value is not None:
        # Quantity type: attempt numeric
        value_numeric = _parse_float(value)
        # Keep value_text as original string for fidelity
    elif unit is None:
        # Category type: no numeric
        value_numeric = None
        value_text = value

    cur = conn.cursor()
    cur.execute(
        """
        INSERT OR IGNORE INTO health_records
            (import_id, type, value_text, value_numeric, unit, source_name, source_version, device_raw, creation_date, start_date, end_date, fingerprint)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            import_id,
            type_,
            value_text,
            value_numeric,
            unit,
            source_name,
            source_version,
            device_raw,
            creation_date,
            start_date,
            end_date,
            fingerprint,
        ),
    )
    if cur.rowcount == 0:
        return (False, 0, 0)

    record_id = cur.lastrowid
    # Insert metadata
    for k, v in metadata:
        cur.execute(
            "INSERT OR IGNORE INTO health_record_metadata (record_id, mkey, mvalue) VALUES (?, ?, ?)",
            (record_id, k, v),
        )
    # Insert HRV beats
    for seq, (bpm, t) in enumerate(hrv_beats):
        cur.execute(
            "INSERT INTO health_hrv_beats (record_id, seq, bpm, time) VALUES (?, ?, ?, ?)",
            (record_id, seq, bpm, t),
        )

    return (True, len(metadata), len(hrv_beats))


def _handle_workout(elem, import_id: str, conn: sqlite3.Connection) -> bool:
    attrib = elem.attrib
    activity_type = attrib.get("workoutActivityType")
    if not activity_type:
        return False
    duration = _parse_float(attrib.get("duration"))
    duration_unit = attrib.get("durationUnit")
    total_distance = _parse_float(attrib.get("totalDistance"))
    total_distance_unit = attrib.get("totalDistanceUnit")
    total_energy = _parse_float(attrib.get("totalEnergyBurned"))
    total_energy_unit = attrib.get("totalEnergyBurnedUnit")
    source_name = attrib.get("sourceName", "")
    source_version = attrib.get("sourceVersion")
    device_raw = attrib.get("device")
    creation_date = attrib.get("creationDate")
    start_date = attrib.get("startDate", "")
    end_date = attrib.get("endDate", "")

    fingerprint = _fingerprint_workout(
        activity_type=activity_type,
        source_name=source_name,
        source_version=source_version,
        start_date=start_date,
        end_date=end_date,
    )

    cur = conn.cursor()
    cur.execute(
        """
        INSERT OR IGNORE INTO health_workouts
            (import_id, activity_type, duration, duration_unit, total_distance, total_distance_unit, total_energy_burned, total_energy_burned_unit, source_name, source_version, device_raw, creation_date, start_date, end_date, fingerprint)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            import_id,
            activity_type,
            duration,
            duration_unit,
            total_distance,
            total_distance_unit,
            total_energy,
            total_energy_unit,
            source_name,
            source_version,
            device_raw,
            creation_date,
            start_date,
            end_date,
            fingerprint,
        ),
    )
    if cur.rowcount == 0:
        return False

    workout_id = cur.lastrowid
    seq_event = 0
    seq_route = 0
    for child in elem:
        if child.tag == "MetadataEntry":
            k = child.get("key", "")
            v = child.get("value", "")
            if k:
                cur.execute(
                    "INSERT OR IGNORE INTO health_workout_metadata (workout_id, mkey, mvalue) VALUES (?, ?, ?)",
                    (workout_id, k, v),
                )
        elif child.tag == "WorkoutEvent":
            cur.execute(
                "INSERT INTO health_workout_events (workout_id, seq, type, date, duration, duration_unit) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    workout_id,
                    seq_event,
                    child.get("type", ""),
                    child.get("date", ""),
                    _parse_float(child.get("duration")),
                    child.get("durationUnit"),
                ),
            )
            seq_event += 1
        elif child.tag == "WorkoutStatistics":
            cur.execute(
                "INSERT INTO health_workout_statistics (workout_id, type, start_date, end_date, average, minimum, maximum, sum, unit) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    workout_id,
                    child.get("type", ""),
                    child.get("startDate", ""),
                    child.get("endDate", ""),
                    _parse_float(child.get("average")),
                    _parse_float(child.get("minimum")),
                    _parse_float(child.get("maximum")),
                    _parse_float(child.get("sum")),
                    child.get("unit"),
                ),
            )
        elif child.tag == "WorkoutRoute":
            # WorkoutRoute may contain FileReference children
            file_path: str | None = None
            for sub in child:
                if sub.tag == "FileReference":
                    file_path = sub.get("path")
                    break
            cur.execute(
                "INSERT INTO health_workout_routes (workout_id, seq, source_name, source_version, device_raw, creation_date, start_date, end_date, file_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    workout_id,
                    seq_route,
                    child.get("sourceName"),
                    child.get("sourceVersion"),
                    child.get("device"),
                    child.get("creationDate"),
                    child.get("startDate"),
                    child.get("endDate"),
                    file_path,
                ),
            )
            seq_route += 1

    return True


def _handle_activity_summary(elem, import_id: str, conn: sqlite3.Connection) -> bool:
    attrib = dict(elem.attrib)
    date_components = attrib.get("dateComponents")
    if not date_components:
        return False
    # Store raw XML and JSON
    try:
        import xml.etree.ElementTree as ET

        raw_xml = ET.tostring(elem, encoding="unicode")
    except Exception:
        raw_xml = str(attrib)
    raw_json = json.dumps(attrib, ensure_ascii=False)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT OR IGNORE INTO health_activity_summaries (import_id, date_components, raw_xml, raw_json)
        VALUES (?, ?, ?, ?)
        """,
        (import_id, date_components, raw_xml, raw_json),
    )
    return cur.rowcount != 0


def _handle_ecg_files(export_dir: Path, import_id: str, conn: sqlite3.Connection) -> int:
    ecg_dir = export_dir / "electrocardiograms"
    if not ecg_dir.is_dir():
        return 0
    count = 0
    for csv_path in sorted(ecg_dir.glob("*.csv")):
        header = _parse_ecg_csv_header(csv_path)
        # File metadata
        try:
            file_size = csv_path.stat().st_size
        except OSError:
            file_size = None
        # sha256 of file
        sha256 = None
        try:
            import hashlib

            h = hashlib.sha256()
            with open(csv_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    h.update(chunk)
            sha256 = h.hexdigest()
        except OSError:
            sha256 = None
        # Relative path for portability
        try:
            rel = csv_path.relative_to(export_dir).as_posix()
        except ValueError:
            rel = str(csv_path)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO health_ecg
                (import_id, file_path, file_name, recorded_at, classification, symptoms, software_version, device, sample_rate_hz, lead, unit, sha256, file_size)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                import_id,
                rel,
                csv_path.name,
                header.get("recorded_at"),
                header.get("classification"),
                header.get("symptoms"),
                header.get("software_version"),
                header.get("device"),
                header.get("sample_rate_hz"),
                header.get("lead"),
                header.get("unit"),
                sha256,
                file_size,
            ),
        )
        count += 1
    if count:
        conn.commit()
    return count
