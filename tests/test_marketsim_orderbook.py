"""Unit tests for the marketsim limit order book."""

from __future__ import annotations

import pytest

from marketsim.orderbook import LimitOrderBook, Order, Side


def _order(agent: str, side: Side, qty: float, price: float | None = None, n: int = 0) -> Order:
    return Order(order_id=f"{agent}-{n}", agent_id=agent, symbol="ACME", side=side, quantity=qty, price=price)


def test_crossed_buy_matches_at_resting_ask_price():
    book = LimitOrderBook("ACME")
    book.add(_order("a", Side.ASK, 10, 101.0), step=0)
    trades = book.add(_order("b", Side.BID, 10, 102.0), step=1)
    assert len(trades) == 1
    assert trades[0].price == 101.0  # resting price, not the taker's
    assert trades[0].quantity == 10
    assert trades[0].buyer_id == "b" and trades[0].seller_id == "a"
    assert book.best_bid() is None and book.best_ask() is None


def test_partial_fill_leaves_remainder_resting():
    book = LimitOrderBook("ACME")
    book.add(_order("a", Side.ASK, 10, 101.0), step=0)
    trades = book.add(_order("b", Side.BID, 4, 102.0), step=1)
    assert len(trades) == 1 and trades[0].quantity == 4
    assert book.best_ask() == 101.0
    assert book.depth(Side.ASK) == [(101.0, 6.0)]


def test_price_priority_better_price_fills_first():
    book = LimitOrderBook("ACME")
    book.add(_order("a", Side.ASK, 5, 102.0), step=0)
    book.add(_order("b", Side.ASK, 5, 101.0), step=0)
    trades = book.add(_order("c", Side.BID, 5, 103.0), step=1)
    assert len(trades) == 1
    assert trades[0].price == 101.0  # best (lowest) ask first
    assert trades[0].seller_id == "b"


def test_time_priority_earlier_order_fills_first():
    book = LimitOrderBook("ACME")
    book.add(_order("a", Side.ASK, 5, 101.0), step=0)
    book.add(_order("b", Side.ASK, 5, 101.0), step=0)
    trades = book.add(_order("c", Side.BID, 5, 101.0), step=1)
    assert len(trades) == 1
    assert trades[0].seller_id == "a"  # earlier seq first
    assert book.depth(Side.ASK) == [(101.0, 5.0)]


def test_non_crossing_limit_rests():
    book = LimitOrderBook("ACME")
    trades = book.add(_order("a", Side.BID, 10, 99.0), step=0)
    assert trades == []
    assert book.best_bid() == 99.0
    assert book.quote().mid is None  # one-sided book has no mid


def test_market_order_sweeps_and_discards_remainder():
    book = LimitOrderBook("ACME")
    book.add(_order("a", Side.ASK, 5, 101.0), step=0)
    book.add(_order("b", Side.ASK, 5, 102.0), step=0)
    trades = book.add(_order("c", Side.BID, 12, None), step=1)
    assert [t.price for t in trades] == [101.0, 102.0]
    assert sum(t.quantity for t in trades) == 10
    assert book.best_ask() is None  # remainder discarded, never rests


def test_market_sell_into_empty_book_trades_nothing():
    book = LimitOrderBook("ACME")
    trades = book.add(_order("a", Side.ASK, 10, None), step=0)
    assert trades == []


def test_cancel_agent_orders():
    book = LimitOrderBook("ACME")
    book.add(_order("mm", Side.BID, 10, 99.0), step=0)
    book.add(_order("mm", Side.ASK, 10, 101.0), step=0)
    book.add(_order("x", Side.BID, 5, 98.0), step=0)
    assert book.cancel_agent_orders("mm") == 2
    assert book.best_bid() == 98.0 and book.best_ask() is None


def test_wrong_symbol_rejected():
    book = LimitOrderBook("ACME")
    with pytest.raises(ValueError, match="wrong symbol|sent to"):
        book.add(Order(order_id="o", agent_id="a", symbol="BETA", side=Side.BID, quantity=1, price=1.0))
