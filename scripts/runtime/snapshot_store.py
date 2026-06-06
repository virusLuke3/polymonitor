#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SQLite-backed snapshot cache for panel-friendly API payloads."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional


class SnapshotStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = str(Path(db_path).expanduser())
        self._lock = threading.Lock()
        self._initialized = False

    def _connect(self) -> sqlite3.Connection:
        path = Path(self.db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            conn = self._connect()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS panel_snapshots (
                        namespace TEXT NOT NULL,
                        cache_key TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        updated_at INTEGER NOT NULL,
                        expires_at INTEGER NOT NULL,
                        PRIMARY KEY (namespace, cache_key)
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS agent_node_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_id TEXT NOT NULL,
                        lens TEXT NOT NULL,
                        node TEXT NOT NULL,
                        input_hash TEXT,
                        output_hash TEXT,
                        output_json TEXT,
                        model TEXT,
                        tokens_json TEXT,
                        latency_ms INTEGER,
                        status TEXT,
                        error TEXT,
                        evidence_refs_json TEXT,
                        started_at TEXT,
                        finished_at TEXT,
                        created_at INTEGER NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_agent_node_events_run_node
                    ON agent_node_events(run_id, node, created_at)
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS agent_forecast_memory (
                        memory_key TEXT PRIMARY KEY,
                        lens TEXT NOT NULL,
                        run_id TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        created_at INTEGER NOT NULL,
                        updated_at INTEGER NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_agent_forecast_memory_lens_updated
                    ON agent_forecast_memory(lens, updated_at DESC)
                    """
                )
                conn.commit()
                self._initialized = True
            finally:
                conn.close()

    def get(self, namespace: str, cache_key: str) -> Optional[Any]:
        self._ensure_schema()
        now = int(time.time())
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT payload_json, expires_at
                FROM panel_snapshots
                WHERE namespace = ? AND cache_key = ?
                LIMIT 1
                """,
                (namespace, cache_key),
            ).fetchone()
            if row is None:
                return None
            if int(row["expires_at"] or 0) <= now:
                return None
            return json.loads(str(row["payload_json"]))
        finally:
            conn.close()

    def get_stale(self, namespace: str, cache_key: str) -> Optional[Any]:
        self._ensure_schema()
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT payload_json
                FROM panel_snapshots
                WHERE namespace = ? AND cache_key = ?
                LIMIT 1
                """,
                (namespace, cache_key),
            ).fetchone()
            if row is None:
                return None
            return json.loads(str(row["payload_json"]))
        finally:
            conn.close()

    def get_latest_stale(self, namespace: str, *, exclude_cache_key: Optional[str] = None) -> Optional[Any]:
        self._ensure_schema()
        conn = self._connect()
        try:
            params: tuple[Any, ...]
            where_clause = "namespace = ?"
            params = (namespace,)
            if exclude_cache_key:
                where_clause += " AND cache_key != ?"
                params = (namespace, exclude_cache_key)
            row = conn.execute(
                f"""
                SELECT payload_json
                FROM panel_snapshots
                WHERE {where_clause}
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                params,
            ).fetchone()
            if row is None:
                return None
            return json.loads(str(row["payload_json"]))
        finally:
            conn.close()

    def set(self, namespace: str, cache_key: str, payload: Any, ttl_seconds: int) -> None:
        self._ensure_schema()
        now = int(time.time())
        expires_at = now + max(1, int(ttl_seconds))
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO panel_snapshots(namespace, cache_key, payload_json, updated_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(namespace, cache_key) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at,
                    expires_at = excluded.expires_at
                """,
                (namespace, cache_key, json.dumps(payload, ensure_ascii=True, default=str), now, expires_at),
            )
            conn.commit()
        finally:
            conn.close()

    def record_agent_node_events(self, events: list[dict[str, Any]]) -> None:
        if not events:
            return
        self._ensure_schema()
        now = int(time.time())
        rows = []
        for event in events:
            if not isinstance(event, dict):
                continue
            rows.append((
                str(event.get("runId") or ""),
                str(event.get("lens") or ""),
                str(event.get("node") or ""),
                event.get("inputHash"),
                event.get("outputHash"),
                json.dumps(event.get("outputJson") or {}, ensure_ascii=True, default=str),
                event.get("model"),
                json.dumps(event.get("tokens") or event.get("usage") or {}, ensure_ascii=True, default=str),
                int(event.get("latencyMs") or 0),
                event.get("status"),
                event.get("error"),
                json.dumps(event.get("evidenceRefs") or [], ensure_ascii=True, default=str),
                event.get("startedAt"),
                event.get("finishedAt"),
                now,
            ))
        if not rows:
            return
        conn = self._connect()
        try:
            conn.executemany(
                """
                INSERT INTO agent_node_events(
                    run_id, lens, node, input_hash, output_hash, output_json, model,
                    tokens_json, latency_ms, status, error, evidence_refs_json,
                    started_at, finished_at, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()
        finally:
            conn.close()

    def get_agent_node_events(self, run_id: str) -> list[dict[str, Any]]:
        self._ensure_schema()
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT *
                FROM agent_node_events
                WHERE run_id = ?
                ORDER BY id ASC
                """,
                (run_id,),
            ).fetchall()
            output = []
            for row in rows:
                output.append({
                    "runId": row["run_id"],
                    "lens": row["lens"],
                    "node": row["node"],
                    "inputHash": row["input_hash"],
                    "outputHash": row["output_hash"],
                    "outputJson": json.loads(row["output_json"] or "{}"),
                    "model": row["model"],
                    "tokens": json.loads(row["tokens_json"] or "{}"),
                    "latencyMs": row["latency_ms"],
                    "status": row["status"],
                    "error": row["error"],
                    "evidenceRefs": json.loads(row["evidence_refs_json"] or "[]"),
                    "startedAt": row["started_at"],
                    "finishedAt": row["finished_at"],
                    "createdAt": row["created_at"],
                })
            return output
        finally:
            conn.close()

    def upsert_agent_forecast_memory(self, memories: list[dict[str, Any]]) -> None:
        if not memories:
            return
        self._ensure_schema()
        now = int(time.time())
        rows = []
        for item in memories:
            if not isinstance(item, dict):
                continue
            key = str(item.get("memoryKey") or item.get("key") or "").strip()
            if not key:
                continue
            rows.append((
                key,
                str(item.get("lens") or "overview"),
                str(item.get("runId") or ""),
                json.dumps(item, ensure_ascii=True, default=str),
                now,
                now,
            ))
        if not rows:
            return
        conn = self._connect()
        try:
            conn.executemany(
                """
                INSERT INTO agent_forecast_memory(memory_key, lens, run_id, payload_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(memory_key) DO UPDATE SET
                    lens = excluded.lens,
                    run_id = excluded.run_id,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                rows,
            )
            conn.commit()
        finally:
            conn.close()

    def get_agent_forecast_memory(self, lens: str, limit: int = 24) -> list[dict[str, Any]]:
        self._ensure_schema()
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT payload_json
                FROM agent_forecast_memory
                WHERE lens = ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (lens, max(1, int(limit))),
            ).fetchall()
            return [json.loads(str(row["payload_json"])) for row in rows]
        finally:
            conn.close()
