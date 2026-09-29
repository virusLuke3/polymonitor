from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from flask import Blueprint, jsonify


@dataclass(frozen=True)
class DataQualityRouteDependencies:
    get_market_data_quality_payload: Callable[[], dict[str, Any]]


def create_data_quality_blueprint(dependencies: DataQualityRouteDependencies) -> Blueprint:
    bp = Blueprint("data_quality_routes", __name__)

    @bp.route("/data-quality/markets", methods=["GET"])
    def api_market_data_quality():
        return jsonify(dependencies.get_market_data_quality_payload())

    return bp
