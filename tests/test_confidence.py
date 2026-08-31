"""source_confidence is measurable fields only — never an LLM."""

from __future__ import annotations

import inspect

import pytest

from eve_miro.core.evaluation.confidence import (
    MEASURABLE_FIELDS,
    SOURCE_CONFIDENCE_WEIGHTS,
    source_confidence,
    source_confidence_from_fields,
)
from eve_miro.core.evaluation.reality_check import reliability_from_freshness


def test_weights_sum_to_one():
    assert abs(sum(SOURCE_CONFIDENCE_WEIGHTS.values()) - 1.0) < 1e-12
    assert MEASURABLE_FIELDS == (
        "reliability",
        "freshness",
        "completeness",
        "cross_source_agreement",
        "historical_accuracy",
    )


def test_source_confidence_known_weighted_mean():
    # 0.25*1 + 0.20*0.5 + 0.20*1 + 0.20*0.5 + 0.15*0 = 0.65
    got = source_confidence(
        reliability=1.0,
        freshness=0.5,
        completeness=1.0,
        cross_source_agreement=0.5,
        historical_accuracy=0.0,
    )
    assert abs(got - 0.65) < 1e-12
    assert source_confidence(
        reliability=1, freshness=1, completeness=1, cross_source_agreement=1, historical_accuracy=1
    ) == 1.0
    assert source_confidence(
        reliability=0, freshness=0, completeness=0, cross_source_agreement=0, historical_accuracy=0
    ) == 0.0


def test_rejects_out_of_range_and_missing_fields():
    with pytest.raises(ValueError):
        source_confidence(
            reliability=1.2,
            freshness=0.5,
            completeness=1.0,
            cross_source_agreement=0.5,
            historical_accuracy=0.5,
        )
    assert source_confidence_from_fields({"reliability": 1.0, "freshness": 1.0}) is None
    assert (
        source_confidence_from_fields(
            {
                "reliability": 1.0,
                "freshness": 1.0,
                "completeness": 1.0,
                "cross_source_agreement": 1.0,
                "historical_accuracy": 1.0,
            }
        )
        == 1.0
    )


def test_formula_is_not_an_llm():
    src = inspect.getsource(source_confidence)
    body = src.split('"""', 2)[-1] if '"""' in src else src
    assert "openai" not in body.lower()
    assert "anthropic" not in body.lower()
    assert "prompt(" not in body.lower()
    assert "*" in body and "reliability" in body


def test_reliability_report_attaches_confidence_when_fields_present():
    report = reliability_from_freshness(
        {
            "usgs": {
                "age_seconds": 60,
                "complete": True,
                "event_count": 3,
                "reliability": 0.8,
                "cross_source_agreement": 0.9,
                "historical_accuracy": 0.7,
            }
        }
    )
    assert "usgs" in report.source_confidence
    assert 0.0 <= report.source_confidence["usgs"] <= 1.0
