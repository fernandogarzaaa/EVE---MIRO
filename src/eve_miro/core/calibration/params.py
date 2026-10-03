"""Calibration parameter vector for the marketsim archetypes.

The nine free parameters map onto existing archetype constructor kwargs
(no duplication: a single PARAM_SPECS table is the source of truth).
Bounds are enforced by a logit transform to the unit hypercube so the
optimizer runs unconstrained. Integer parameters are rounded on use.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from marketsim.agents import (
    FundamentalTrader,
    MarketMaker,
    MomentumTrader,
    NoiseTrader,
    TraderAgent,
)

# RMSC-04 population ratios (ABIDES reference): 1000 noise : 102 value :
# 12 momentum : 2 market makers. Used to split the non-noise agents.
RMSC_VALUE = 102.0
RMSC_MOMENTUM = 12.0
RMSC_MM = 2.0

AGENTS_TOTAL = 32


@dataclass(frozen=True)
class ParamSpec:
    name: str
    lo: float
    hi: float
    start: float
    integer: bool = False
    maps_to: str = ""


PARAM_SPECS: tuple[ParamSpec, ...] = (
    ParamSpec("mm_spread_bps", 2.0, 100.0, 20.0, maps_to="MarketMaker(spread_bps)"),
    ParamSpec("mm_skew_k", 0.0, 10.0, 2.0, maps_to="MarketMaker(skew_k)"),
    ParamSpec("mm_size", 5.0, 200.0, 25.0, maps_to="MarketMaker(size)"),
    ParamSpec("noise_trade_prob", 0.05, 0.9, 0.35, maps_to="NoiseTrader(trade_prob)"),
    ParamSpec("noise_size", 10.0, 300.0, 50.0, maps_to="NoiseTrader(size)"),
    ParamSpec("momentum_lookback", 2, 20, 5, integer=True, maps_to="MomentumTrader(lookback)"),
    ParamSpec("momentum_threshold", 0.0005, 0.02, 0.003, maps_to="MomentumTrader(threshold)"),
    ParamSpec("fund_tolerance", 0.002, 0.05, 0.01, maps_to="FundamentalTrader(tolerance)"),
    ParamSpec("noise_frac", 0.5, 0.95, 0.85, maps_to="runner: noise agent fraction"),
)

PARAM_NAMES: tuple[str, ...] = tuple(s.name for s in PARAM_SPECS)
PARAM_INDEX: dict[str, int] = {s.name: i for i, s in enumerate(PARAM_SPECS)}

_EPS = 1e-9


def _to_unit(x: float, lo: float, hi: float) -> float:
    t = min(max((x - lo) / (hi - lo), _EPS), 1.0 - _EPS)
    return math.log(t / (1.0 - t))


def _from_unit(u: float, lo: float, hi: float) -> float:
    t = 1.0 / (1.0 + math.exp(-max(min(u, 50.0), -50.0)))
    return lo + t * (hi - lo)


@dataclass(frozen=True)
class CalibrationParams:
    """Parameter vector in PARAM_SPECS order."""

    values: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.values) != len(PARAM_SPECS):
            raise ValueError(
                f"expected {len(PARAM_SPECS)} parameters, got {len(self.values)}"
            )
        for spec, v in zip(PARAM_SPECS, self.values):
            if not (spec.lo <= v <= spec.hi):
                raise ValueError(f"{spec.name}={v} outside [{spec.lo}, {spec.hi}]")

    @classmethod
    def from_dict(cls, d: dict[str, float]) -> "CalibrationParams":
        try:
            return cls(tuple(float(d[s.name]) for s in PARAM_SPECS))
        except KeyError as exc:
            raise ValueError(f"missing calibration parameter: {exc}") from exc

    @classmethod
    def from_unit(cls, u: tuple[float, ...] | list[float]) -> "CalibrationParams":
        if len(u) != len(PARAM_SPECS):
            raise ValueError(f"expected {len(PARAM_SPECS)} unit values, got {len(u)}")
        vals = []
        for spec, ui in zip(PARAM_SPECS, u):
            v = _from_unit(float(ui), spec.lo, spec.hi)
            vals.append(float(round(v)) if spec.integer else v)
        return cls(tuple(vals))

    @classmethod
    def starting_point(cls) -> "CalibrationParams":
        return cls(tuple(s.start for s in PARAM_SPECS))

    def to_unit(self) -> tuple[float, ...]:
        return tuple(_to_unit(v, s.lo, s.hi) for v, s in zip(self.values, PARAM_SPECS))

    def to_dict(self) -> dict[str, float]:
        return {s.name: v for s, v in zip(PARAM_SPECS, self.values)}

    def __getitem__(self, name: str) -> float:
        return self.values[PARAM_INDEX[name]]

    # -- mapping onto archetype constructor kwargs (single mapping table) --
    def market_maker_kwargs(self) -> dict[str, float]:
        return {
            "spread_bps": self["mm_spread_bps"],
            "skew_k": self["mm_skew_k"],
            "size": self["mm_size"],
        }

    def noise_kwargs(self) -> dict[str, float]:
        return {"trade_prob": self["noise_trade_prob"], "size": self["noise_size"]}

    def momentum_kwargs(self) -> dict[str, float]:
        return {
            "lookback": int(round(self["momentum_lookback"])),
            "threshold": self["momentum_threshold"],
        }

    def fundamental_kwargs(self, fair_value: float) -> dict[str, float]:
        return {"tolerance": self["fund_tolerance"], "fair_value": fair_value}

    def agent_counts(self, total: int = AGENTS_TOTAL) -> dict[str, int]:
        """Agent counts from noise_frac; remainder split by RMSC-04 ratios.

        Guarantees at least one market maker, one momentum and one
        fundamental trader; the noise count absorbs rounding.
        """
        n_mm = 1
        n_mom = 1
        rest_for_value = total - n_mm - n_mom
        n_noise = int(round(total * self["noise_frac"]))
        n_noise = min(max(n_noise, 0), rest_for_value - 1)
        n_val = rest_for_value - n_noise
        return {
            "market_maker": n_mm,
            "momentum": n_mom,
            "noise": n_noise,
            "fundamental": n_val,
        }


def build_agents(
    params: CalibrationParams,
    symbol: str,
    seed: int,
    total: int = AGENTS_TOTAL,
    initial_price: float = 100.0,
) -> list[TraderAgent]:
    """Build the archetype population for one calibration replication."""
    counts = params.agent_counts(total)
    agents: list[TraderAgent] = []
    i = 0
    for _ in range(counts["market_maker"]):
        agents.append(MarketMaker(f"mm-{i:03d}", symbol, seed=seed + i, **params.market_maker_kwargs()))
        i += 1
    for _ in range(counts["momentum"]):
        agents.append(MomentumTrader(f"mom-{i:03d}", symbol, seed=seed + i, **params.momentum_kwargs()))
        i += 1
    for _ in range(counts["noise"]):
        agents.append(NoiseTrader(f"noise-{i:03d}", symbol, seed=seed + i, **params.noise_kwargs()))
        i += 1
    for _ in range(counts["fundamental"]):
        agents.append(
            FundamentalTrader(
                f"fund-{i:03d}", symbol, seed=seed + i,
                **params.fundamental_kwargs(initial_price),
            )
        )
        i += 1
    return agents
