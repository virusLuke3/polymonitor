"""Explicit configuration for self-hosted Polygon reads."""

from data_sources import env_str, require_self_hosted_polygon_rpc_url


def get_rpc_url() -> str:
    value = env_str("POLYMARKET_RPC_URL")
    if not value:
        raise RuntimeError("POLYMARKET_RPC_URL is required; configure the self-hosted Polygon RPC tunnel")
    return require_self_hosted_polygon_rpc_url(value)
