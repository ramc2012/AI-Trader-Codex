"""Watchlist parsing helpers."""

from src.api.routes.watchlist import _parse_last_trade_price


def test_parse_last_trade_price_with_dollar_format() -> None:
    value = _parse_last_trade_price("LAST TRADE: $263.75 (AS OF MAR 4, 2026)")
    assert value == 263.75


def test_parse_last_trade_price_with_plain_numeric_format() -> None:
    value = _parse_last_trade_price("Last Sale 685.02")
    assert value == 685.02


def test_parse_last_trade_price_ignores_date_noise() -> None:
    value = _parse_last_trade_price("AS OF MAR 4, 2026")
    assert value == 0.0
