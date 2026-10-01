from __future__ import annotations
import hashlib, json
from datetime import datetime, timedelta, timezone
from .normalize import identity, permission, utc


def ensure_schema(storage):
    from api.services.query_service import _ensure_content_tables

    _ensure_content_tables(storage)
    conn = storage.get_connection(storage.database_path)
    try:
        for sql in (
            "CREATE TABLE IF NOT EXISTS content_source_state (source_id TEXT PRIMARY KEY, state_json TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS content_versions (content_id TEXT NOT NULL, version TEXT NOT NULL, payload TEXT NOT NULL, first_fetched_at TEXT NOT NULL, PRIMARY KEY(content_id,version))",
            "CREATE TABLE IF NOT EXISTS content_discoveries (content_id TEXT NOT NULL, source_id TEXT NOT NULL, first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, PRIMARY KEY(content_id,source_id))",
        ):
            conn.execute(sql)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_content_public_time ON content_items(provider,published_at)")
        conn.commit()
    finally:
        conn.close()


def source_states(storage):
    if not storage.table_exists("content_source_state"):
        return {}
    return {
        row["source_id"]: json.loads(row["state_json"])
        for row in storage.query_all("SELECT * FROM content_source_state")
    }


def save_state(storage, source_id, state):
    conn = storage.get_connection(storage.database_path)
    try:
        conn.execute(
            "INSERT INTO content_source_state(source_id,state_json) VALUES (?,?) ON CONFLICT(source_id) DO UPDATE SET state_json=excluded.state_json",
            (source_id, json.dumps(state)),
        )
        conn.commit()
    finally:
        conn.close()


def persist(storage, source, items, now):
    counts = {"new": 0, "updated": 0, "duplicate": 0, "excluded": 0, "public": 0}
    conn = storage.get_connection(storage.database_path)
    try:
        for item in items:
            if not source.get("storage_allowed"):
                counts["excluded"] += 1
                continue
            item = {
                **item,
                "publisher_id": source["publisher_id"],
                "source_id": source["source_id"],
                "permission_basis": source["permission_basis"],
            }
            allowed, reason = permission(source, item)
            item.update(display_allowed=allowed, permission_reason=reason)
            item.pop("rights_text", None)
            content_id = identity(source, item)
            prior = conn.execute(
                "SELECT raw_payload,created_at FROM content_items WHERE id=?", (content_id,)
            ).fetchone()
            old = json.loads(prior["raw_payload"]) if prior else {}
            item["source_id"] = old.get("source_id") or item["source_id"]
            item["topics"] = sorted(set(old.get("topics", []) + item.get("topics", [])))
            # Entry sources are discovery provenance, not article revisions.
            version_data = {
                k: v
                for k, v in item.items()
                if k not in {"source_id", "fetched_at", "first_seen_at", "article_rights_checked_at"}
            }
            version = hashlib.sha256(json.dumps(version_data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            if old.get("content_version") == version:
                counts["duplicate"] += 1
            else:
                counts["updated" if prior else "new"] += 1
                item.update(
                    first_seen_at=old.get("first_seen_at") or now,
                    fetched_at=now,
                    content_version=version,
                    version_first_fetched_at=now,
                )
                raw = json.dumps(item, ensure_ascii=False)
                conn.execute(
                    "INSERT INTO content_versions(content_id,version,payload,first_fetched_at) VALUES (?,?,?,?) ON CONFLICT(content_id,version) DO NOTHING",
                    (content_id, version, raw, now),
                )
                conn.execute(
                    "INSERT INTO content_items(id,content_type,provider,source,category,topic_id,title,url,published_at,summary,raw_payload,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET topic_id=excluded.topic_id,title=excluded.title,url=excluded.url,summary=excluded.summary,published_at=excluded.published_at,raw_payload=excluded.raw_payload,updated_at=excluded.updated_at",
                    (
                        content_id,
                        "news",
                        "free-public",
                        source["publisher_name"],
                        source["source_kind"],
                        "free:" + source["publisher_id"] + (":" + item["event_id"] if source['publisher_id']=='nhc' else ""),
                        item["title"],
                        item["url"],
                        item.get("published_at"),
                        item.get("summary") or None,
                        raw,
                        item["first_seen_at"],
                        now,
                    ),
                )
            conn.execute(
                "INSERT INTO content_discoveries(content_id,source_id,first_seen_at,last_seen_at) VALUES (?,?,?,?) ON CONFLICT(content_id,source_id) DO UPDATE SET last_seen_at=excluded.last_seen_at",
                (content_id, source["source_id"], now, now),
            )
            counts["public" if allowed else "excluded"] += 1
        conn.commit()
    finally:
        conn.close()
    return counts


def prune(storage, config, now):
    # Only this worker's owned records. Existing legacy/history records are untouched.
    conn = storage.get_connection(storage.database_path)
    try:
        cutoff = (
            datetime.fromisoformat(now.replace("Z", "+00:00")) - timedelta(days=config["retention_days"])
        ).isoformat()
        ids = [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM content_items WHERE provider='free-public' AND updated_at < ?", (cutoff,)
            ).fetchall()
        ]
        ids += [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM content_items WHERE provider='free-public' ORDER BY updated_at DESC LIMIT 20000 OFFSET ?",
                (config["max_items"],),
            ).fetchall()
        ]
        for cid in ids:
            conn.execute("DELETE FROM content_versions WHERE content_id=?", (cid,))
            conn.execute("DELETE FROM content_discoveries WHERE content_id=?", (cid,))
            conn.execute("DELETE FROM content_links WHERE content_id=?", (cid,))
            conn.execute("DELETE FROM content_items WHERE id=?", (cid,))
        conn.execute("DELETE FROM content_versions WHERE first_fetched_at < ?", (cutoff,))
        # Bound per-item revisions without deleting the current article.
        conn.execute(
            "DELETE FROM content_versions WHERE (content_id,version) IN (SELECT content_id,version FROM (SELECT content_id,version,ROW_NUMBER() OVER(PARTITION BY content_id ORDER BY first_fetched_at DESC) AS rn FROM content_versions) ranked WHERE rn>?)",
            (config["max_versions_per_item"],),
        )
        conn.commit()
    finally:
        conn.close()
