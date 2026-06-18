from __future__ import annotations

from quant.backtest.runners import selectors


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params):
        self.sql = sql
        self.params = params

    def fetchall(self):
        return list(self.rows)


class FakeConnection:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return FakeCursor(self.rows)


def test_postgres_selector_query_retries_connection_timeout(monkeypatch):
    attempts = {"count": 0}

    def fake_postgres_connection(readonly=True):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("connection timeout expired")
        return FakeConnection([{"market_id": 1}])

    monkeypatch.setattr(selectors, "postgres_connection", fake_postgres_connection)
    monkeypatch.setattr(selectors.time, "sleep", lambda _seconds: None)

    rows = selectors._query_postgres_rows("select 1", ())

    assert rows == [{"market_id": 1}]
    assert attempts["count"] == 2


def test_postgres_selector_query_does_not_retry_non_connection_errors(monkeypatch):
    attempts = {"count": 0}

    def fake_postgres_connection(readonly=True):
        attempts["count"] += 1
        raise RuntimeError("syntax error")

    monkeypatch.setattr(selectors, "postgres_connection", fake_postgres_connection)

    try:
        selectors._query_postgres_rows("select broken", ())
    except RuntimeError as exc:
        assert "syntax error" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")

    assert attempts["count"] == 1
