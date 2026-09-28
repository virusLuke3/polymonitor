from trade import rpc_utils


def test_rpc_session_can_ignore_environment_proxies(monkeypatch):
    monkeypatch.setenv("POLYDATA_RPC_TRUST_ENV_PROXY", "0")

    session = rpc_utils.build_retry_session()

    assert session is not None
    assert session.trust_env is False


def test_rpc_session_trusts_environment_by_default(monkeypatch):
    monkeypatch.delenv("POLYDATA_RPC_TRUST_ENV_PROXY", raising=False)

    session = rpc_utils.build_retry_session()

    assert session is not None
    assert session.trust_env is True
