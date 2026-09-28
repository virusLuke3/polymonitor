"""Register already-composed HTTP blueprints."""

from collections.abc import Iterable
from flask import Blueprint, Flask


def register_blueprints(app: Flask, blueprints: Iterable[Blueprint]) -> None:
    for blueprint in blueprints:
        app.register_blueprint(blueprint)
