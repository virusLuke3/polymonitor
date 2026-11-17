from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Protocol

import requests

from .formatters import (
    crypto_price_map,
    format_alert_created,
    format_alert_removed,
    format_alerts,
    format_market_search,
    format_pnl_coverage,
    format_signals,
    format_wallet,
    help_text,
    is_address,
    market_search_action_links,
    signal_action_links,
    start_text,
)
from .models import BotReply, CommandRequest
from .state import BotState


class BotApi(Protocol):
    def search_markets(self, query: str, *, limit: int = 5): ...
    def alpha_signals(self, *, limit: int = 5): ...
    def wallet_summary(self, address: str, *, days: int = 30): ...
    def wallet_trades(self, address: str, *, limit: int = 5): ...
    def pnl(self, address: str): ...
    def crypto_markets(self): ...


def _keyboard(rows: list[list[tuple[str, str]]]) -> dict:
    keyboard = []
    for row in rows:
        buttons = []
        for label, target in row:
            if target.startswith("http"):
                buttons.append({"text": label, "url": target})
            else:
                buttons.append({"text": label, "callback_data": target})
        keyboard.append(buttons)
    return {"inline_keyboard": keyboard}


def _market_search_keyboard(payload: dict) -> dict | None:
    links = market_search_action_links(payload)
    if not links:
        return None
    return _keyboard([links[:2]])


def _signal_keyboard(payload: dict) -> dict | None:
    links = signal_action_links(payload)
    if not links:
        return None
    return _keyboard([links[:2], [("Open Workspace", "https://www.polymonitor.club")]])


COMMAND_ALIASES = {
    "帮助": "help",
}


def _usage(command: str) -> BotReply:
    usages = {
        "market": "请使用：/market nba 或 /market bitcoin",
        "wallet": "请使用：/wallet 0x...",
        "pnl": "请使用：/pnl 0x...",
        "signal": "请使用：/signal polymarket",
        "alert": "请使用：/alert BTC 95000",
    }
    return BotReply(f"⚠️ {command}\n{usages.get(command, '请使用 /help 查看命令')}")


def _service_error(label: str) -> BotReply:
    return BotReply(f"⚠️ {label}\n服务暂时不可用，稍后再试。")


def _parse_alert_args(args: str) -> tuple[str, float] | None:
    parts = args.split()
    if len(parts) < 2:
        return None
    symbol = parts[0].strip().upper().replace("-USD", "")
    try:
        threshold = float(parts[1].replace(",", ""))
    except ValueError:
        return None
    if not symbol or threshold <= 0:
        return None
    return symbol, threshold


def handle_command(request: CommandRequest, api: BotApi, state: Optional[BotState] = None) -> BotReply:
    command = COMMAND_ALIASES.get(request.command, request.command)
    args = request.args.strip()
    if command == "start":
        if state is not None:
            state.record_user(chat_id=request.chat_id, user_id=request.user_id)
            state.save()
        return BotReply(start_text(), link_preview=False, reply_markup=_keyboard([[("Help", "/help")]]))
    if command == "help":
        return BotReply(help_text())
    if command == "market":
        if not args:
            return _usage("market")
        try:
            payload = api.search_markets(args, limit=5)
            return BotReply(
                format_market_search(args, payload),
                link_preview=False,
                reply_markup=_market_search_keyboard(payload),
            )
        except requests.RequestException:
            return _service_error("Market")
    if command == "signal":
        topic = args or "polymarket"
        try:
            payload = api.alpha_signals(limit=5)
            return BotReply(format_signals(topic, payload), link_preview=True, reply_markup=_signal_keyboard(payload))
        except requests.RequestException:
            return _service_error("Signal")
    if command == "wallet":
        if not args or not is_address(args.split()[0]):
            return _usage("wallet")
        address = args.split()[0].lower()
        try:
            summary = api.wallet_summary(address, days=30)
            trades = api.wallet_trades(address, limit=5)
        except requests.RequestException:
            return BotReply(
                "\n".join(
                    [
                        "⚠️ Wallet",
                        "地址服务暂时不可用。",
                        f"地址：{address[:6]}...{address[-4:]}",
                    ]
                )
            )
        return BotReply(format_wallet(address, summary, trades), link_preview=False)
    if command == "pnl":
        if not args or not is_address(args.split()[0]):
            return _usage("pnl")
        address = args.split()[0].lower()
        payload = {}
        try:
            payload = api.pnl(address)
        except requests.RequestException:
            payload = {}
        return BotReply(format_pnl_coverage(address, payload), link_preview=False)
    if command == "alert":
        if state is None:
            return BotReply("⚠️ Alert\n状态存储不可用。")
        parsed = _parse_alert_args(args)
        if parsed is None:
            return _usage("alert")
        symbol, threshold = parsed
        current_price = None
        try:
            current_price = crypto_price_map(api.crypto_markets()).get(symbol)
        except requests.RequestException:
            current_price = None
        direction = "above" if current_price is None or threshold >= current_price else "below"
        alert = {
            "id": state.next_alert_id(),
            "chatId": request.chat_id,
            "userId": request.user_id,
            "symbol": symbol,
            "threshold": threshold,
            "direction": direction,
            "createdPrice": current_price,
            "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "enabled": True,
        }
        state.add_alert(alert)
        state.save()
        return BotReply(format_alert_created(alert))
    if command == "alerts":
        if state is None:
            return BotReply("⚠️ Alerts\n状态存储不可用。")
        return BotReply(format_alerts(state.alerts_for(chat_id=request.chat_id, user_id=request.user_id)))
    if command in {"alert_remove", "alertremove", "remove_alert"}:
        if state is None:
            return BotReply("⚠️ Alert\n状态存储不可用。")
        try:
            alert_id = int(args.split()[0])
        except (IndexError, ValueError):
            return BotReply("⚠️ Alert\n请使用：/alert_remove <id>")
        removed = state.remove_alert(alert_id=alert_id, chat_id=request.chat_id, user_id=request.user_id)
        state.save()
        return BotReply(format_alert_removed(alert_id, removed))
    return BotReply(f"⚠️ Unknown command: /{command}\n使用 /help 查看可用命令。")
