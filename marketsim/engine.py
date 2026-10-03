"""MarketSimEngine: agent-based market simulator behind SimulationEngine.

Builds instruments from the WorldState market slice
(``Economy.indicators["market_snapshot"]["tickers"]``) and/or the Scenario, runs trader
archetypes against per-instrument limit order books, applies shock
interventions, and finalizes SIMULATED price trajectories.

This engine never stubs: without instruments it raises
``EngineNotConfigured`` (fail closed). All output prices are SIMULATED;
only the initial prices come from OBSERVED input context.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from eve_miro.core.simulation.engine import (
    AgentAction,
    Simulation,
    SimulationResult,
    SimulationStep,
)
from eve_miro.core.simulation.scenarios import Scenario
from eve_miro.core.world.events import ProvenanceKind
from eve_miro.core.world.state import Population, WorldState
from eve_miro.core.world.temporal import as_utc, iso, parse_offset
from eve_miro.errors import EngineNotConfigured
from marketsim.agents import (
    ARCHETYPES,
    MarketMaker,
    MarketView,
    TraderAgent,
)
from marketsim.orderbook import LimitOrderBook, Order, Side, Trade

MARKET_DISCLAIMER = (
    "SIMULATED. Agent-based scenario projections under stated assumptions, "
    "not a forecast of market prices. Initial prices are observed input "
    "context; every subsequent price is simulated. Never mix with OBSERVED prices."
)

DEFAULT_AGENT_MIX = {
    "market_maker": 0.10,
    "momentum": 0.30,
    "noise": 0.40,
    "fundamental": 0.20,
}

# Canonical market snapshot: WorldState Economy.indicators["market_snapshot"]
# (built by Phase 1's eve_miro.core.world.markets.build_market_snapshot).
# Per-ticker entries live under ["tickers"] with fields like "latest_close",
# "realized_vol_5d", "realized_vol_20d". This function is the single
# reconciliation point: it maps that shape onto the engine's internal
# {ticker: {"price": float, "realized_vol": {window: float}}}.
MARKET_SNAPSHOT_KEY = "market_snapshot"


def read_market_slice(world: WorldState) -> dict[str, dict[str, Any]]:
    """Extract per-ticker {price, realized_vol} from the WorldState.

    Single reconciliation point if the provider field names change.
    """
    try:
        indicators = world.economy.indicators or {}
    except AttributeError:
        return {}
    if not isinstance(indicators, dict):
        return {}
    snapshot = indicators.get(MARKET_SNAPSHOT_KEY) or {}
    tickers = snapshot.get("tickers") if isinstance(snapshot, dict) else None
    if not isinstance(tickers, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for ticker, entry in tickers.items():
        if not isinstance(entry, dict):
            continue
        price = entry.get("latest_close")
        if price is None:
            continue
        vols: dict[str, float] = {}
        for window in ("5d", "20d"):
            v = entry.get(f"realized_vol_{window}")
            if isinstance(v, (int, float)) and v is not None:
                vols[window] = float(v)
        try:
            out[str(ticker)] = {"price": float(price), "realized_vol": vols}
        except (TypeError, ValueError):
            continue
    return out


@dataclass
class _InstrumentState:
    symbol: str
    book: LimitOrderBook
    mid_history: list[float] = field(default_factory=list)
    fair_value: float = 100.0
    volume_history: list[float] = field(default_factory=list)
    trade_count_history: list[int] = field(default_factory=list)
    last_trade: float | None = None


@dataclass
class _VolSpike:
    multiplier: float
    until_hour: int


@dataclass
class _SellPressure:
    qty_per_hour: float
    until_hour: int


@dataclass
class _SimState:
    instruments: dict[str, _InstrumentState]
    agents: dict[str, TraderAgent]
    agent_symbols: dict[str, str]
    vol_spikes: dict[str, _VolSpike] = field(default_factory=dict)
    sell_pressure: dict[str, _SellPressure] = field(default_factory=dict)
    primary_symbol: str = ""


class MarketSimEngine:
    """SimulationEngine for market shock scenarios. Pure Python, no keys."""

    name = "marketsim"

    def __init__(
        self,
        scenario: Scenario | None = None,
        *,
        artifacts: list[dict[str, Any]] | None = None,
        url: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.scenario = scenario
        self.artifacts = list(artifacts or [])
        self._states: dict[str, _SimState] = {}

    # -- initialize ------------------------------------------------------
    async def initialize(self, world: WorldState, population: Population) -> Simulation:
        sc = self.scenario
        market_slice = read_market_slice(world)
        conditions = dict(sc.conditions) if sc else {}

        symbols = [str(s) for s in (conditions.get("symbols") or [])] or sorted(market_slice)
        if not symbols:
            raise EngineNotConfigured(
                "marketsim: no instruments: WorldState has no "
                f"Economy.indicators[{MARKET_SNAPSHOT_KEY!r}] and the scenario "
                "provides no conditions.symbols"
            )

        initial_prices = {str(k): float(v) for k, v in (conditions.get("initial_prices") or {}).items()}
        fair_values = {str(k): float(v) for k, v in (conditions.get("fair_values") or {}).items()}

        n = population.synthetic_n or (sc.population if sc else 50)
        seed = sc.random_seed if sc else 48291
        origin = sc.origin if sc else world.timestamp
        hours = sc.simulated_hours if sc else 24
        cutoff = sc.cutoff if sc else world.information_cutoff

        instruments: dict[str, _InstrumentState] = {}
        for sym in symbols:
            price = market_slice.get(sym, {}).get("price", initial_prices.get(sym, 100.0))
            price = float(price)
            if price <= 0:
                raise EngineNotConfigured(f"marketsim: non-positive initial price for {sym}")
            book = LimitOrderBook(sym)
            # Bootstrap the book so step 0 has a mid: resting quotes around price.
            book.add(
                Order(order_id="bootstrap-bid", agent_id="bootstrap", symbol=sym,
                      side=Side.BID, quantity=1000.0, price=round(price * 0.999, 4)),
                step=-1,
            )
            book.add(
                Order(order_id="bootstrap-ask", agent_id="bootstrap", symbol=sym,
                      side=Side.ASK, quantity=1000.0, price=round(price * 1.001, 4)),
                step=-1,
            )
            instruments[sym] = _InstrumentState(
                symbol=sym, book=book, fair_value=fair_values.get(sym, price),
                mid_history=[price],
            )

        mix = dict(conditions.get("agent_mix") or DEFAULT_AGENT_MIX)
        agents = self._build_agents(symbols, n, seed, mix)

        sim_id = f"marketsim_{world.world_id}_{seed}"
        self._states[sim_id] = _SimState(
            instruments=instruments,
            agents={a.agent_id: a for a in agents},
            agent_symbols={a.agent_id: a.symbol for a in agents},
            primary_symbol=symbols[0],
        )

        disclaimer = (
            sc.disclaimer
            if sc is not None and getattr(sc, "disclaimer", None)
            else MARKET_DISCLAIMER
        )
        return Simulation(
            id=sim_id,
            world_id=world.world_id,
            scenario_name=sc.name if sc else "ad_hoc_market",
            status="created",
            information_cutoff=cutoff,
            origin=origin,
            hours=hours,
            seed=seed,
            population_n=len(agents),
            personas=[],
            interventions=[i.model_dump() for i in (sc.interventions if sc else [])],
            scenario_type="market",
            world_snapshot={
                "markets": market_slice,
                "symbols": symbols,
                "note": "OBSERVED input context; subsequent prices are SIMULATED.",
                "timestamp": world.timestamp.isoformat(),
            },
            learning_artifacts=list(self.artifacts),
            disclaimer=disclaimer,
        )

    def _build_agents(
        self, symbols: list[str], n: int, seed: int, mix: dict[str, float]
    ) -> list[TraderAgent]:
        kinds = [k for k in ARCHETYPES if mix.get(k, 0) > 0] or ["noise"]
        weights = [max(mix.get(k, 0.0), 0.0) for k in kinds]
        total = sum(weights) or 1.0
        # Stratified assignment: exact proportional counts (remainder to the
        # largest weight), then a seeded shuffle. Robust across seeds.
        by_weight = sorted(range(len(kinds)), key=lambda i: -weights[i])
        counts: dict[str, int] = {}
        assigned = 0
        for pos, i in enumerate(by_weight):
            if pos == len(by_weight) - 1:
                counts[kinds[i]] = n - assigned
            else:
                c = int(round(n * weights[i] / total))
                counts[kinds[i]] = c
                assigned += c
        seq: list[str] = []
        for kind, c in counts.items():
            seq.extend([kind] * max(c, 0))
        while len(seq) < n:
            seq.append(kinds[by_weight[0]])
        seq = seq[:n]
        rng = random.Random(seed ^ 0x5EED)
        rng.shuffle(seq)
        agents: list[TraderAgent] = []
        for i, kind in enumerate(seq):
            symbol = symbols[i % len(symbols)]
            agents.append(ARCHETYPES[kind](f"{kind}-{i:04d}", symbol, seed=seed + i * 131))
        return agents

    # -- stepping ---------------------------------------------------------
    def _state(self, simulation: Simulation) -> _SimState:
        try:
            return self._states[simulation.id]
        except KeyError as exc:
            raise EngineNotConfigured(
                f"marketsim: no state for simulation {simulation.id}; initialize first"
            ) from exc

    def _intervention_hour(self, raw: dict[str, Any], origin: datetime) -> int | None:
        try:
            t = parse_offset(str(raw.get("timestamp", "")), origin)
        except (ValueError, TypeError):
            return None
        return int((t - origin).total_seconds() // 3600)

    def _apply_interventions(self, simulation: Simulation, state: _SimState, hour: int) -> None:
        for raw in simulation.interventions:
            if self._intervention_hour(raw, simulation.origin) != hour:
                continue
            itype = str(raw.get("type", ""))
            extra = dict(raw.get("extra") or {})
            if itype == "sell_shock":
                symbol = str(extra.get("symbol", state.primary_symbol))
                qty = float(extra.get("quantity", 1000.0))
                # A large seller works the order over time (a real liquidation
                # is not one print). duration_hours=1 preserves single-shot.
                duration = max(int(extra.get("duration_hours", 1)), 1)
                inst = state.instruments.get(symbol)
                if inst is None or qty <= 0:
                    continue
                if duration == 1:
                    inst.book.add(
                        Order(order_id=f"shock-{hour}", agent_id=f"shock:{itype}",
                              symbol=symbol, side=Side.ASK, quantity=qty, price=None),
                        step=hour,
                    )
                else:
                    state.sell_pressure[symbol] = _SellPressure(qty / duration, hour + duration)
            elif itype == "volatility_spike":
                symbol = str(extra.get("symbol", state.primary_symbol))
                mult = float(extra.get("multiplier", 3.0))
                dur = int(extra.get("duration_hours", 12))
                if symbol in state.instruments and mult > 0:
                    state.vol_spikes[symbol] = _VolSpike(mult, hour + dur)
            elif itype == "rate_shock":
                pct = float(extra.get("fair_value_pct_change", 0.0))
                targets = [str(s) for s in (extra.get("symbols") or [])] or list(state.instruments)
                for sym in targets:
                    inst = state.instruments.get(sym)
                    if inst is not None:
                        inst.fair_value = inst.fair_value * (1.0 + pct)

    def _apply_sell_pressure(self, state: _SimState, hour: int) -> list[Trade]:
        """Persistent liquidator: market-sells every hour while active."""
        trades: list[Trade] = []
        for symbol, sp in list(state.sell_pressure.items()):
            if hour >= sp.until_hour:
                del state.sell_pressure[symbol]
                continue
            inst = state.instruments.get(symbol)
            if inst is None:
                continue
            trades.extend(
                inst.book.add(
                    Order(order_id=f"liquidator-{hour}", agent_id="liquidator",
                          symbol=symbol, side=Side.ASK, quantity=sp.qty_per_hour, price=None),
                    step=hour,
                )
            )
        return trades

    async def step(self, simulation: Simulation) -> SimulationStep:
        state = self._state(simulation)
        hour = simulation.cursor_hour
        t = simulation.origin + timedelta(hours=hour)
        self._apply_interventions(simulation, state, hour)
        step_trades: list[Trade] = self._apply_sell_pressure(state, hour)

        actions: list[AgentAction] = []
        for agent_id in sorted(state.agents):
            agent = state.agents[agent_id]
            inst = state.instruments[agent.symbol]
            book = inst.book
            if isinstance(agent, MarketMaker):
                book.cancel_agent_orders(agent_id)
            spike = state.vol_spikes.get(agent.symbol)
            vol_mult = spike.multiplier if spike and hour < spike.until_hour else 1.0
            pressure = state.sell_pressure.get(agent.symbol)
            flow_shock = -1.0 if (pressure and hour < pressure.until_hour) else 0.0
            quote = book.quote()
            if quote.mid is not None:
                mid = quote.mid
            elif inst.last_trade is not None:
                mid = inst.last_trade
            else:
                mid = inst.mid_history[-1] if inst.mid_history else None
            view = MarketView(
                symbol=agent.symbol,
                mid=mid,
                spread=quote.spread,
                mid_history=list(inst.mid_history),
                inventory=agent.inventory,
                fair_value=inst.fair_value,
                step=hour,
                vol_multiplier=vol_mult,
                flow_shock=flow_shock,
            )
            orders = agent.decide(view)
            acted: str = "hold"
            for order in orders:
                trades = book.add(order, step=hour)
                step_trades.extend(trades)
                for tr in trades:
                    buyer = state.agents.get(tr.buyer_id)
                    seller = state.agents.get(tr.seller_id)
                    if buyer is not None:
                        buyer.on_fill(Side.BID, tr.quantity)
                    if seller is not None:
                        seller.on_fill(Side.ASK, tr.quantity)
                if order.side == Side.BID:
                    acted = "buy"
                elif order.side == Side.ASK:
                    acted = "sell"
            actions.append(
                AgentAction(
                    agent_id=agent_id,
                    t=t,
                    hour=hour,
                    action=acted,  # type: ignore[arg-type]
                    wind_speed=0.0,
                    congestion=0.0,
                    warning_active=False,
                    warning_received=False,
                    outcome=f"{acted}_order" if acted != "hold" else "held",
                    provenance_kind=ProvenanceKind.SIMULATED,
                )
            )

        mids: dict[str, float] = {}
        for sym, inst in state.instruments.items():
            quote = inst.book.quote()
            hour_trades = [tr for tr in step_trades if tr.symbol == sym]
            if hour_trades:
                inst.last_trade = hour_trades[-1].price
            if quote.mid is not None:
                mid = quote.mid
            elif inst.last_trade is not None:
                mid = inst.last_trade
            else:
                mid = inst.mid_history[-1]
            inst.mid_history.append(mid)
            inst.volume_history.append(sum(tr.quantity for tr in hour_trades))
            inst.trade_count_history.append(len(hour_trades))
            mids[sym] = mid

        primary_mid = mids[state.primary_symbol]
        step = SimulationStep(
            hour=hour,
            t=t,
            wind_speed=0.0,
            precipitation=0.0,
            congestion=0.0,
            warning_active=False,
            evacuated_n=0,
            stuck_n=0,
            actions=actions,
            price=round(primary_mid, 4),
        )
        simulation.steps.append(step)
        simulation.cursor_hour += 1
        return step

    # -- finalize ----------------------------------------------------------
    async def run(self, simulation: Simulation, until: datetime) -> SimulationResult:
        simulation.status = "running"
        until = as_utc(until)
        # The closed loop reassigns sim.id after initialize() for traceability
        # (sim_<world>_<scenario>_<seed>). Re-key the engine state when the
        # original id is unambiguously recoverable; otherwise fail closed.
        if simulation.id not in self._states:
            original = f"marketsim_{simulation.world_id}_{simulation.seed}"
            if original in self._states:
                self._states[simulation.id] = self._states.pop(original)
        max_hours = simulation.hours
        while simulation.cursor_hour < max_hours:
            t = simulation.origin + timedelta(hours=simulation.cursor_hour)
            if t > until:
                break
            await self.step(simulation)
        simulation.status = "completed" if simulation.cursor_hour >= max_hours else "paused"
        return self._result(simulation)

    @staticmethod
    def _max_drawdown(mids: list[float]) -> float:
        peak = -math.inf
        worst = 0.0
        for m in mids:
            peak = max(peak, m)
            if peak > 0:
                worst = min(worst, m / peak - 1.0)
        return worst

    def _result(self, simulation: Simulation) -> SimulationResult:
        state = self._state(simulation)
        predicted_series: dict[str, list[float]] = {}
        predicted_times: list[str] = []
        per_symbol: dict[str, dict[str, Any]] = {}
        for sym, inst in state.instruments.items():
            # mid_history[0] is the observed seed price; series[1:] are SIMULATED.
            series = [round(m, 4) for m in inst.mid_history[1:]]
            predicted_series[sym] = series
            start = inst.mid_history[0]
            end = inst.mid_history[-1]
            per_symbol[sym] = {
                "seed_price": round(start, 4),
                "final_mid": round(end, 4),
                "return": round(end / start - 1.0, 6) if start > 0 else 0.0,
                "max_drawdown": round(self._max_drawdown(inst.mid_history), 6),
                "total_volume": round(sum(inst.volume_history), 2),
                "total_trades": sum(inst.trade_count_history),
                "final_fair_value": round(inst.fair_value, 4),
            }
        for st in simulation.steps:
            predicted_times.append(iso(st.t))
        traces: list[dict[str, Any]] = []
        for st in simulation.steps:
            for a in st.actions:
                traces.append(
                    {
                        "simulation_id": simulation.id,
                        "hour": a.hour,
                        "t": iso(a.t),
                        "agent_id": a.agent_id,
                        "symbol": state.agent_symbols.get(a.agent_id),
                        "action": a.action,
                        "outcome": a.outcome,
                        "provenance_kind": a.provenance_kind.value,
                    }
                )
        summary = {
            "hours": len(simulation.steps),
            "symbols": per_symbol,
            "primary_symbol": state.primary_symbol,
            "n_agents": len(state.agents),
            "provenance_kind": ProvenanceKind.SIMULATED.value,
            "disclaimer": simulation.disclaimer,
            "scenario_type": "market",
            "note": "Distributions under scenarios, not price forecasts.",
        }
        return SimulationResult(
            simulation=simulation,
            traces=traces,
            predicted_series=predicted_series,
            predicted_times=predicted_times,
            summary=summary,
        )
