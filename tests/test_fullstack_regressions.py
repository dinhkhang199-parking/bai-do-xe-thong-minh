from pathlib import Path
import sqlite3
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
import api.main as api
from backend import read_queries as read
from scripts import backup_runtime as backup


def test_backup_includes_committed_wal_data(tmp_path,monkeypatch):
    monkeypatch.setattr(backup,'BACKUP_ROOT',tmp_path/'backups')
    source=tmp_path/'parking.db'
    with sqlite3.connect(source) as writer:
        writer.execute('CREATE TABLE sample(id INTEGER)');writer.commit()
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute('INSERT INTO sample VALUES(42)');writer.commit()
        output=backup.create_runtime_backup(tmp_path/'backup.zip',db_path=source,uploads_dir=tmp_path/'uploads')
        with ZipFile(output) as archive:
            restored=tmp_path/'restored.db';restored.write_bytes(archive.read('runtime/parking.db'))
        with sqlite3.connect(restored) as conn:
            assert conn.execute('SELECT id FROM sample').fetchall()==[(42,)]


def test_failed_backup_keeps_previous_complete_archive(tmp_path,monkeypatch):
    monkeypatch.setattr(backup,'BACKUP_ROOT',tmp_path/'backups')
    source=tmp_path/'parking.db'
    with sqlite3.connect(source) as conn:conn.execute('CREATE TABLE sample(id INTEGER)')
    output=tmp_path/'backup.zip';output.write_bytes(b'previous complete archive')
    monkeypatch.setattr(ZipFile,'write',lambda *a,**kw:(_ for _ in ()).throw(OSError('disk write failed')))
    with pytest.raises(OSError):backup.create_runtime_backup(output,db_path=source,uploads_dir=tmp_path/'uploads')
    assert output.read_bytes()==b'previous complete archive'


def test_history_orders_mixed_timezone_formats_by_instant(log_rows):
    database=log_rows([
        dict(ticket_id='OLDER',entry_time='2026-11-03 08:00:00'),
        dict(ticket_id='NEWER',entry_time='2026-11-03T02:00:00Z'),
        dict(ticket_id='INVALID',entry_time='unknown'),
    ])
    assert [row['ticket_id'] for row in read.logs_page(db_path=database)['items']]==['NEWER','OLDER','INVALID']


def test_active_search_is_normalized_but_preserves_letters_and_counts_all_matches(log_rows,monkeypatch):
    log_rows([dict(ticket_id='A',plate_entry='30-AB 123.45'),dict(ticket_id='B',plate_entry='30-A8 123.45'),
        dict(ticket_id='C',plate_entry='30 AB 12345'),dict(ticket_id='R',plate_entry='30-AB 123.45',status='NEEDS_REVIEW')])
    monkeypatch.setattr(api,'API_TOKEN','fixture-read-token')
    client=TestClient(api.app)
    response=client.get('/tickets/active?limit=1&plate=30ab12345&status=IN_PARKING',headers={'x-api-token':'fixture-read-token'})
    assert response.status_code==200
    result=response.json();assert result['total']==2 and result['count']==1
    response=client.get('/tickets/active?q=30a8&status=IN_PARKING',headers={'x-api-token':'fixture-read-token'})
    assert [row['ticket_id'] for row in response.json()['items']]==['B']


def test_unexpected_api_error_has_safe_json_and_request_reference(monkeypatch):
    monkeypatch.setattr(api,'API_TOKEN','fixture-read-token')
    monkeypatch.setattr(read,'logs_page',lambda *a,**kw:(_ for _ in ()).throw(RuntimeError('secret-internal-path')))
    response=TestClient(api.app,raise_server_exceptions=False).get('/logs',headers={'x-api-token':'fixture-read-token'})
    assert response.status_code==500
    assert response.headers.get('X-Request-ID')
    assert 'secret-internal-path' not in response.text
    assert response.json()['error']['code']=='INTERNAL_ERROR'


def test_active_api_defaults_to_fifty_rows_and_empty_identity_search_does_not_match_everything(log_rows,monkeypatch):
    log_rows([dict(ticket_id=f'T{i:04}',plate_entry=f'59-B1 {100+i:03}.45') for i in range(61)])
    monkeypatch.setattr(api,'API_TOKEN','fixture-read-token')
    client=TestClient(api.app);headers={'x-api-token':'fixture-read-token'}
    result=client.get('/tickets/active',headers=headers).json()
    assert result['count']==50 and result['total']==61 and result['limit']==50
    assert client.get('/tickets/active?q=---',headers=headers).json()['total']==0
    assert client.get('/tickets/active?status=COMPLETED',headers=headers).status_code==422


def test_backup_refuses_to_include_its_own_output_directory(tmp_path,monkeypatch):
    monkeypatch.setattr(backup,'BACKUP_ROOT',tmp_path/'backups')
    uploads=tmp_path/'uploads';uploads.mkdir()
    with pytest.raises(ValueError,match='outside'):
        backup.create_runtime_backup(uploads/'backup.zip',db_path=tmp_path/'missing.db',uploads_dir=uploads)
    assert not (uploads/'backup.zip').exists()
