from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from backend.config import BASE_DIR, DB_PATH, UPLOAD_DIR

BACKUP_ROOT = BASE_DIR / "backups"


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _ensure_parent(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _validate_db_readable(db_path: Path) -> None:
    if not db_path.exists():
        return
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("SELECT name FROM sqlite_master LIMIT 1").fetchall()
    finally:
        conn.close()


def build_backup_manifest(db_path: Path, uploads_dir: Path) -> dict:
    upload_files = (
        sorted([p for p in uploads_dir.rglob("*") if p.is_file()]) if uploads_dir.exists() else []
    )
    return {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "base_dir": str(BASE_DIR),
        "db_path": str(db_path),
        "db_exists": db_path.exists(),
        "uploads_dir": str(uploads_dir),
        "upload_file_count": len(upload_files),
    }


def create_runtime_backup(
    output_path: Path | None = None, *, db_path: Path = DB_PATH, uploads_dir: Path = UPLOAD_DIR
) -> Path:
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    target = output_path or (
        BACKUP_ROOT / f"its-runtime-backup-{_timestamp()}-{uuid4().hex[:8]}.zip"
    )
    target = _ensure_parent(target)
    if target.resolve().is_relative_to(uploads_dir.resolve()):
        raise ValueError("Backup output must be outside the uploads directory")

    _validate_db_readable(db_path)

    with tempfile.TemporaryDirectory(prefix=".its-backup-", dir=target.parent) as staging:
        snapshot = Path(staging) / "database.sqlite3"
        if db_path.exists():
            # SQLite's online backup includes committed WAL pages while the app runs.
            with (
                closing(
                    sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
                ) as source,
                closing(sqlite3.connect(snapshot)) as destination,
            ):
                source.backup(destination)
                if destination.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                    raise ValueError("Backup database failed integrity check")
        upload_files = (
            sorted(path for path in uploads_dir.rglob("*") if path.is_file())
            if uploads_dir.exists()
            else []
        )
        manifest = build_backup_manifest(db_path, uploads_dir)
        manifest["upload_file_count"] = len(upload_files)
        staged_archive = Path(staging) / "backup.zip"
        with ZipFile(staged_archive, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            if snapshot.exists():
                archive.write(snapshot, arcname=f"runtime/{db_path.name}")
            for file_path in upload_files:
                archive.write(
                    file_path,
                    arcname=(
                        Path("runtime/uploads") / file_path.relative_to(uploads_dir)
                    ).as_posix(),
                )
        # A disk/read failure leaves an earlier backup intact.
        os.replace(staged_archive, target)
    return target


def main() -> None:
    backup_path = create_runtime_backup()
    print(f"Created runtime backup: {backup_path}")


if __name__ == "__main__":
    main()
