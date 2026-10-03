"""Unit tests for marketsim trader archetypes."""

from __future__ import annotations

from marketsim.agents import (
    FundamentalTrader,
    MarketMaker,
    MarketView,
    MomentumTrader,
    NoiseTrader,
)
from marketsim.orderbook import Side


def _view(**kw) -> MarketView:
    base = dict(
        symbol="ACME",
        mid=100.0,
        spread=0.2,
        mid_history=[100.0] * 10,
        inventory=0.0,
        fair_value=100.0,
        step=0,
    )
    base.update(kw)
    return MarketView(**base)


def test_market_maker_quotes_ladder_straddling_mid():
    mm = MarketMaker("mm-1", "ACME", size=50.0, seed=1, spread_bps=20.0)
    orders = mm.decide(_view())
    assert len(orders) == 6  # 3-level ladder each side
    bids = sorted((o for o in orders if o.side == Side.BID), key=lambda o: -o.price)
    asks = sorted((o for o in orders if o.side == Side.ASK), key=lambda o: o.price)
    assert all(o.price < 100.0 for o in bids)
    assert all(o.price > 100.0 for o in asks)
    assert bids[0].quantity == 50.0 and bids[2].quantity == 200.0  # deeper = larger
    # Ladder widens with depth.
    assert bids[0].price > bids[1].price > bids[2].price


def test_market_maker_skews_against_long_inventory():
    mm = MarketMaker("mm-1", "ACME", seed=1)
    mm.inventory = 4000.0  # long: should shade quotes down
    orders = mm.decide(_view())
    mm2 = MarketMaker("mm-2", "ACME", seed=1)
    neutral = mm2.decide(_view())
    bid_skewed = next(o for o in orders if o.side == Side.BID)
    bid_neutral = next(o for o in neutral if o.side == Side.BID)
    assert bid_skewed.price < bid_neutral.price


def test_market_maker_respects_inventory_limit():
    mm = MarketMaker("mm-1", "ACME", seed=1, inventory_limit=100.0)
    mm.inventory = 100.0
    orders = mm.decide(_view())
    assert len(orders) == 3  # ladder on the reducing side only
    assert all(o.side == Side.ASK for o in orders)  # only reducing side


def test_momentum_buys_uptrend_sells_downtrend():
    up = [100.0 + i for i in range(10)]
    down = [100.0 - i for i in range(10)]
    mom = MomentumTrader("mom-1", "ACME", seed=1, lookback=5, threshold=0.003)
    assert mom.decide(_view(mid=109.0, mid_history=up))[0].side == Side.BID
    assert mom.decide(_view(mid=91.0, mid_history=down))[0].side == Side.ASK
    flat = [100.0] * 10
    assert mom.decide(_view(mid_history=flat)) == []


def test_fundamental_buys_below_fair_sells_above():
    f = FundamentalTrader("f-1", "ACME", seed=1, fair_value=100.0, tolerance=0.01)
    assert f.decide(_view(mid=98.0))[0].side == Side.BID
    assert f.decide(_view(mid=102.0))[0].side == Side.ASK
    assert f.decide(_view(mid=100.5)) == []  # inside tolerance


def test_noise_trader_is_seeded_deterministic():
    n1 = NoiseTrader("n-1", "ACME", seed=42)
    n2 = NoiseTrader("n-1", "ACME", seed=42)
    v = _view()
    assert [(o.side, o.quantity) for o in n1.decide(v)] == [(o.side, o.quantity) for o in n2.decide(v)]


def test_agents_return_nothing_without_mid():
    v = _view(mid=None, mid_history=[])
    assert MarketMaker("m", "ACME", seed=1).decide(v) == []
    assert NoiseTrader("n", "ACME", seed=1).decide(v) == []
    assert FundamentalTrader("f", "ACME", seed=1).decide(v) == []
