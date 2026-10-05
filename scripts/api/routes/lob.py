from __future__ import annotations

from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from api.services import lob_service
from typing import Callable, Any

from flask import Blueprint, jsonify, request


@dataclass(frozen=True)
class LobRouteDependencies:
    get_runtime_lob_payload: Callable[..., dict[str, Any]]
    get_runtime_lob_by_token_payload: Callable[..., dict[str, Any]]
    get_runtime_lob_batch_token_payload: Callable[..., dict[str, Any]] = partial(lob_service.get_runtime_lob_by_token_payload, read_timeout_seconds=3.0)


def create_lob_blueprint(dependencies: LobRouteDependencies) -> Blueprint:
    bp = Blueprint("lob_routes", __name__)

    @bp.after_request
    def prevent_stale_http_cache(response):
        response.headers["Cache-Control"] = "no-store"
        return response

    @bp.route("/runtime/lob/<int:market_id>", methods=["GET"])
    def api_runtime_lob_by_market_id(market_id: int):
        payload = dependencies.get_runtime_lob_payload(market_id)
        status_code = int(payload.pop("_status", 200))
        return jsonify(payload), status_code

    @bp.route("/runtime/lob/books", methods=["GET"])
    def api_runtime_lob_books():
        raw = request.args.get("tokens") or ""
        tokens = list(dict.fromkeys(raw.split(",")))
        if not tokens or len(tokens) > 24 or any(not token.isdecimal() or len(token) > 100 for token in tokens):
            return jsonify({"error": "Expected 1 to 24 numeric token ids"}), 400

        def read(token):
            try:
                payload = dependencies.get_runtime_lob_batch_token_payload(token)
                return token, payload
            except Exception:
                # A failed interval cannot discard successful neighbouring books.
                return token, {"bookStatus": "unavailable", "yes": {"tokenId": token, "bookStatus": "unavailable"}}

        with ThreadPoolExecutor(max_workers=4) as pool:
            books = dict(pool.map(read, tokens))
        return jsonify({"books": books})

    @bp.route("/runtime/lob/token/<token_id>", methods=["GET"])
    def api_runtime_lob_by_token(token_id: str):
        payload = dependencies.get_runtime_lob_by_token_payload(
            token_id,
            no_token_id=request.args.get("noTokenId") or "",
            market_title=request.args.get("title") or "",
            market_id=request.args.get("marketId", type=int),
        )
        status_code = int(payload.pop("_status", 200))
        return jsonify(payload), status_code

    @bp.route("/runtime/lob/token/<token_id>/snapshots", methods=["GET"])
    def api_runtime_lob_snapshots_by_token(token_id: str):
        return jsonify(
            {
                "status": "unavailable",
                "code": "lob_history_retired",
                "error": "Historical LOB snapshots are owned by market-data archives",
                "items": [],
                "tokenId": token_id,
            }
        ), 410

    return bp
