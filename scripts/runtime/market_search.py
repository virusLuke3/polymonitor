"""Read-only market linking using the same bounded registry query as the API."""
from api.services.market_service import MarketPanelReader, market_rows, read_query


def build_market_search(settings):
    def query(sql, params=()):
        return read_query(lambda path: settings.database.connect(path, readonly=True, connect_timeout=3),
                          settings.database.sqlite_path, sql, params)

    def search(text, limit=10):
        text = str(text or "").strip()[:160]
        if not text:
            return {"items": []}
        if text.startswith("0x") and len(text) == 66:
            where = "m.condition_id = ?"
        else:
            where = "m.active IS TRUE AND m.closed IS FALSE AND to_tsvector('simple', coalesce(m.title,'') || ' ' || coalesce(m.slug,'') || ' ' || coalesce(m.category,'')) @@ plainto_tsquery('simple', ?)"
        rows = market_rows(query, where, (text,), limit=min(50, max(1, int(limit))))
        return {"items": [MarketPanelReader._item(row) for row in rows]}
    return search
