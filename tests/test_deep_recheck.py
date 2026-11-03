from datetime import datetime, timezone, timedelta
import sqlite3

import pytest

from backend import db, parking_service as parking


@pytest.mark.parametrize('table', ['parking_events', 'audit_logs'])
@pytest.mark.parametrize('operation', ['entry', 'exit', 'resolve', 'cancel'])
def test_ticket_transition_rolls_back_when_history_cannot_be_written(tmp_path, monkeypatch, table, operation):
    database = tmp_path / 'atomic.db'
    db.init_db(database)
    monkeypatch.setattr(parking, 'DB_PATH', database)
    ticket = None
    if operation != 'entry':
        ticket = parking.vehicle_entry('59-B1 123.45')['ticket_id']
    if operation == 'resolve':
        parking.vehicle_exit(ticket, '59-B1 123.46')
    with sqlite3.connect(database) as conn:
        before = conn.execute('SELECT * FROM parking_logs').fetchall()
        counts = [conn.execute(f'SELECT count(*) FROM {name}').fetchone()[0]
                  for name in ('parking_events', 'audit_logs', 'ticket_billing')]
        conn.execute(f"CREATE TRIGGER simulate_history_failure BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT, 'fixture history unavailable'); END")
    actions = {
        'entry': lambda: parking.vehicle_entry('59-B1 123.45'),
        'exit': lambda: parking.vehicle_exit(ticket, '59-B1 123.45'),
        'resolve': lambda: parking.resolve_review_ticket(ticket, 'MARK_MATCH', note='fixture review'),
        'cancel': lambda: parking.cancel_ticket(ticket, reason='fixture cancel'),
    }
    with pytest.raises(sqlite3.DatabaseError, match='fixture history unavailable'):
        actions[operation]()
    with sqlite3.connect(database) as conn:
        assert conn.execute('SELECT * FROM parking_logs').fetchall() == before
        assert [conn.execute(f'SELECT count(*) FROM {name}').fetchone()[0]
                for name in ('parking_events', 'audit_logs', 'ticket_billing')] == counts


def test_parking_time_is_vietnam_time_even_when_host_clock_uses_utc(tmp_path, monkeypatch):
    database = tmp_path / 'clock.db'
    db.init_db(database)
    monkeypatch.setattr(parking, 'DB_PATH', database)

    class UtcHost(datetime):
        @classmethod
        def now(cls, tz=None):
            instant = datetime(2026, 11, 3, 20, 15, tzinfo=timezone.utc)
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    monkeypatch.setattr(parking, 'datetime', UtcHost)
    entry = parking.vehicle_entry('59-B1 123.45')
    timestamp = datetime.fromisoformat(entry['entry_time'])
    assert timestamp.utcoffset() == timedelta(hours=7)
    assert timestamp.isoformat() == '2026-11-04T03:15:00+07:00'
    assert entry['ticket_id'].startswith('T20261104031500')


@pytest.mark.parametrize('history', ['events', 'audit'])
def test_legacy_utc_history_and_new_aware_records_sort_by_instant(tmp_path, history):
    from backend import read_queries
    database = tmp_path / 'history.db'
    db.init_db(database)
    table, key = ('parking_events', 'event_type') if history == 'events' else ('audit_logs', 'action')
    with sqlite3.connect(database) as conn:
        conn.executemany(f'INSERT INTO {table}({key},created_at) VALUES(?,?)', [
            ('newer', '2026-11-03 23:30:00'),  # SQLite's legacy UTC default
            ('older', '2026-11-04T00:00:00+07:00'),
        ])
    function = read_queries.events_page if history == 'events' else read_queries.audit_page
    rows = function(db_path=database)['items']
    assert [row[key] for row in rows] == ['newer', 'older']
    assert rows[0]['created_at'] == '2026-11-03T23:30:00+00:00'
