from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def decoder(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "scripts/market/market_decoder.py"
    spec = importlib.util.spec_from_file_location("tested_market_decoder", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CONDITION = "0xeb4b906b2f8cb838c75d28ddc856e22b789cb30af49a7d4490a89e70d86e4dda"
COLLECTION = "0x185ad67ff7bd1f08cb101ace813aecd67ddab3b3457d43e3157372a2fa8ab9a3"
ZERO = "0x" + "00" * 32


@pytest.mark.parametrize("missing", ["web3", "ctf"])
def test_collection_requires_rpc_and_ctf(decoder, missing):
    with pytest.raises(ValueError, match="--use-onchain --rpc-url"):
        decoder.calculate_collection_id(
            ZERO, CONDITION, 1,
            w3=None if missing == "web3" else object(),
            ctf_address=None if missing == "ctf" else decoder.CONDITIONAL_TOKENS_ADDRESS,
        )


def test_collection_failure_never_returns_simplified_hash(decoder):
    contract = Mock()
    contract.functions.getCollectionId.return_value.call.side_effect = TimeoutError("unavailable")
    w3 = SimpleNamespace(eth=SimpleNamespace(contract=lambda **kwargs: contract))
    with pytest.raises(RuntimeError, match="No substitute collection or token ID"):
        decoder.calculate_collection_id(ZERO, CONDITION, 1, w3, decoder.CONDITIONAL_TOKENS_ADDRESS)


def test_verified_collection_produces_actual_ctf_position(decoder):
    contract = Mock()
    contract.functions.getCollectionId.return_value.call.return_value = bytes.fromhex(COLLECTION[2:])
    w3 = SimpleNamespace(eth=SimpleNamespace(contract=lambda **kwargs: contract))
    collection = decoder.calculate_collection_id(ZERO, CONDITION, 1, w3, decoder.CONDITIONAL_TOKENS_ADDRESS)
    contract.functions.getCollectionId.assert_called_once_with(bytes(32), bytes.fromhex(CONDITION[2:]), 1)
    assert collection == COLLECTION
    assert decoder.calculate_position_id(decoder.USDC_E_ADDRESS, collection) == (
        "109288486396417685546996195648291079387115725133891233562493113698307544047098"
    )


def test_market_token_generation_without_rpc_stops_before_output(decoder):
    oracle, question = "0x" + "11" * 20, "0x" + "22" * 32
    condition = decoder.calculate_condition_id(oracle, question)
    with pytest.raises(ValueError, match="on-chain getCollectionId"):
        decoder.calculate_market_tokens(condition, oracle, question)
