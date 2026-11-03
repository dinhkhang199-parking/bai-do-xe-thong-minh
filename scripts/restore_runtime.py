"""Validated, staged restore. Stop the ITS server before restoring runtime data."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import stat
import tempfile
from contextlib import closing
from pathlib import Path, PurePosixPath
from uuid import uuid4
from zipfile import ZipFile

from backend.config import BASE_DIR, DB_PATH, UPLOAD_DIR

MAX_MEMBER_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024
MAX_MEMBERS = 10000


def _validate_db_readable(db_path: Path) -> None:
    with closing(sqlite3.connect(db_path.as_uri() + '?mode=ro', uri=True)) as conn:
        if conn.execute('PRAGMA integrity_check').fetchone() != ('ok',):
            raise ValueError('Backup database failed integrity check')
        if not conn.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 1").fetchone():
            raise ValueError('Backup database has no tables')


def _write_member(archive: ZipFile, member: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with archive.open(member) as source, target.open('xb') as destination:
        shutil.copyfileobj(source, destination, length=1024 * 1024)


def _validated_members(archive: ZipFile) -> list[str]:
    infos = archive.infolist()
    if 'manifest.json' not in archive.namelist():
        raise ValueError('Not a valid ITS backup: missing manifest.json')
    if len(infos) > MAX_MEMBERS or sum(i.file_size for i in infos) > MAX_ARCHIVE_BYTES:
        raise ValueError('Backup archive exceeds restore limits')
    seen = set()
    for info in infos:
        name = info.filename
        path = PurePosixPath(name)
        parts = name.rstrip('/').split('/')
        # ZIP names are POSIX paths; reject alternate Windows spellings too.
        if (not name or name.startswith('/') or '\\' in name or ':' in name or
                any(p in {'', '.', '..'} or p.endswith((' ', '.')) for p in parts) or
                any(p.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *('COM'+str(i) for i in range(1,10)), *('LPT'+str(i) for i in range(1,10))} for p in parts) or
                stat.S_ISLNK(info.external_attr >> 16)):
            raise ValueError('Unsafe backup member path')
        if name != 'manifest.json' and (not parts or parts[0] != 'runtime'):
            raise ValueError('Unexpected backup member')
        key = str(path).casefold()
        if key in seen or info.file_size > MAX_MEMBER_BYTES:
            raise ValueError('Duplicate or oversized backup member')
        seen.add(key)
    names = archive.namelist()
    if archive.getinfo('manifest.json').file_size > 65536:
        raise ValueError('Backup manifest too large')
    try:
        manifest = json.loads(archive.read('manifest.json'))
    except (ValueError, UnicodeError) as exc:
        raise ValueError('Invalid backup manifest') from exc
    if not isinstance(manifest, dict):
        raise ValueError('Invalid backup manifest')
    return names


def validate_backup_archive(archive_path: Path) -> list[str]:
    with ZipFile(archive_path, 'r') as archive:
        return _validated_members(archive)


def _reject_links(path: Path) -> None:
    for part in [path, *path.parents]:
        if part.is_symlink() or getattr(part, 'is_junction', lambda: False)():
            raise ValueError('Restore destination cannot contain symbolic links or junctions')


def restore_runtime_backup(archive_path: Path, *, base_dir: Path = BASE_DIR,
                           db_path: Path = DB_PATH, uploads_dir: Path = UPLOAD_DIR,
                           dry_run: bool = False) -> dict:
    db_path, uploads_dir = Path(db_path).absolute(), Path(uploads_dir).absolute()
    _reject_links(db_path)
    _reject_links(uploads_dir)
    if db_path == uploads_dir or uploads_dir in db_path.parents or db_path in uploads_dir.parents:
        raise ValueError('Database and uploads destinations must be separate')
    with ZipFile(archive_path, 'r') as archive:
        names = _validated_members(archive)
        db_member = f'runtime/{db_path.name}'
        if db_member not in names:
            raise ValueError('Backup does not contain the expected database')
        members = [n for n in names if n.startswith('runtime/uploads/') and not n.endswith('/')]
        allowed = {'manifest.json', db_member}
        if any(n not in allowed and not n.endswith('/') and not n.startswith('runtime/uploads/') for n in names):
            raise ValueError('Unexpected runtime file in backup')
        # No destination writes occur on dry-run, including directory creation.
        if dry_run:
            return {'db_restored': True, 'uploads_restored': len(members), 'dry_run': True}
        if any(Path(str(db_path)+suffix).exists() for suffix in ('-wal','-shm','-journal')):
            raise ValueError('Stop ITS and close database connections before restoring')
        db_path.parent.mkdir(parents=True, exist_ok=True)
        uploads_dir.parent.mkdir(parents=True, exist_ok=True)
        token = uuid4().hex
        recovery_db = db_path.with_name(db_path.name+'.before-restore-'+token)
        recovery_uploads = uploads_dir.with_name(uploads_dir.name+'.before-restore-'+token)
        # Each stage is on the destination filesystem so replacement uses rename.
        with tempfile.TemporaryDirectory(prefix='.its-restore-', dir=db_path.parent) as db_tmp, \
             tempfile.TemporaryDirectory(prefix='.its-restore-', dir=uploads_dir.parent) as uploads_tmp:
            staged_db, staged_uploads = Path(db_tmp)/'database', Path(uploads_tmp)/'uploads'
            _write_member(archive, db_member, staged_db)
            _validate_db_readable(staged_db)
            if uploads_dir.exists():
                for existing in uploads_dir.rglob('*'):
                    _reject_links(existing)
                shutil.copytree(uploads_dir, staged_uploads)
            else:
                staged_uploads.mkdir()
            for member in members:
                relative = PurePosixPath(member).relative_to('runtime/uploads')
                target = staged_uploads.joinpath(*relative.parts)
                if target.exists():
                    if not target.is_file():
                        raise ValueError('Backup member conflicts with an existing directory')
                    target.unlink()  # Only the private staged copy is changed.
                _write_member(archive, member, target)
            moved_db = moved_uploads = installed_db = installed_uploads = False
            try:
                if db_path.exists():
                    os.replace(db_path, recovery_db); moved_db = True
                if uploads_dir.exists():
                    os.replace(uploads_dir, recovery_uploads); moved_uploads = True
                os.replace(staged_db, db_path); installed_db = True
                os.replace(staged_uploads, uploads_dir); installed_uploads = True
            except Exception:
                # Preserve recovery copies outside temporary directories if rollback fails.
                if installed_db:
                    os.replace(db_path, Path(db_tmp)/'failed-database')
                if installed_uploads:
                    os.replace(uploads_dir, Path(uploads_tmp)/'failed-uploads')
                if moved_db:
                    os.replace(recovery_db, db_path)
                if moved_uploads:
                    os.replace(recovery_uploads, uploads_dir)
                raise
    return {'db_restored': True, 'uploads_restored': len(members),
            'recovery_db': str(recovery_db) if moved_db else None,
            'recovery_uploads': str(recovery_uploads) if moved_uploads else None}


def main() -> int:
    parser = argparse.ArgumentParser(description='Stop ITS before restoring. Previous data is retained beside each destination.')
    parser.add_argument('backup')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--yes', action='store_true')
    args = parser.parse_args()
    if not args.dry_run and not args.yes:
        if input("Stop the ITS server first. Type 'yes' to restore: ").strip().lower() != 'yes':
            print('Aborted.'); return 1
    result = restore_runtime_backup(Path(args.backup), dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
