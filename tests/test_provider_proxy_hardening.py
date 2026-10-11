# Regression tests: bracketed-IPv6 no_proxy entries crash httpx client
# construction ("Invalid port: ':1]'), failing every live provider fetch.
# eve_miro.providers.common sanitizes them for the duration of the request.
import os


def test_clean_no_proxy_drops_bracketed_ipv6_only():
    from eve_miro.http_proxy import clean_no_proxy

    cleaned = clean_no_proxy("localhost,127.0.0.1,::1,[::1],198.19.0.1,[fd00::1]")
    assert cleaned == "localhost,127.0.0.1,::1,198.19.0.1"
    assert clean_no_proxy("localhost,127.0.0.1") == "localhost,127.0.0.1"
    assert clean_no_proxy("") == ""


def test_sanitized_proxy_env_restores_after_use(monkeypatch):
    from eve_miro.http_proxy import sanitized_proxy_env

    original = "localhost,[::1],198.19.0.1"
    monkeypatch.setenv("no_proxy", original)
    monkeypatch.setenv("NO_PROXY", original)
    with sanitized_proxy_env():
        assert os.environ["no_proxy"] == "localhost,198.19.0.1"
        assert os.environ["NO_PROXY"] == "localhost,198.19.0.1"
    assert os.environ["no_proxy"] == original
    assert os.environ["NO_PROXY"] == original


async def test_http_get_json_survives_bracketed_no_proxy(monkeypatch):
    """Regression: sandbox no_proxy with '[::1]' crashed httpx client init."""
    import httpx

    from eve_miro.providers.common import http_get_json

    monkeypatch.setenv("no_proxy", "localhost,[::1]")
    seen = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    class FakeClient:
        def __init__(self, **kwargs):
            seen["init_ok"] = True

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, params=None, headers=None):
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    result = await http_get_json("https://example.invalid/x")
    assert result == {"ok": True}
    assert seen["init_ok"]
    assert os.environ["no_proxy"] == "localhost,[::1]"


def test_scenario_trust_describe_sentence_is_grammatical():
    from eve_miro.core.reality.trust_profile import ScenarioTrust

    st = ScenarioTrust(
        scenario_class="sell_shock",
        n_alignments=2,
        drawdown_tolerance=0.02,
        drawdown_within_tol_frac=0.0,
        mean_drawdown_error=0.0414,
        score=0.1,
    )
    text = st.describe()
    assert "within 2.00% of the observed drawdown 0% of the time (0 of 2)" in text
    assert "of observed 0%" not in text
