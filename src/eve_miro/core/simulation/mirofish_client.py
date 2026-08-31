"""HTTP client for the real MiroFish Flask app (`mirofish/backend`).

Walks the registered routes (not invented `/api/predict`):

1. POST /api/graph/ontology/generate  (multipart ``files`` = seed .md)
2. POST /api/graph/build  JSON {project_id}
3. poll GET /api/graph/task/<task_id> until graph ready
4. POST /api/simulation/create JSON {project_id, enable_twitter, enable_reddit}
5. POST /api/simulation/prepare JSON {simulation_id}
6. poll POST /api/simulation/prepare/status
7. POST /api/simulation/start JSON {simulation_id, max_rounds, platform}
8. poll GET /api/simulation/<id>/run-status until done
9. GET /api/simulation/<id>/actions and /timeline

Outputs are SIMULATED. Missing keys or a down server raise EngineNotConfigured.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

from eve_miro.core.simulation.engine import AgentAction, Simulation, SimulationResult, SimulationStep
from eve_miro.core.world.events import ProvenanceKind
from eve_miro.core.world.temporal import as_utc, iso
from eve_miro.errors import EngineNotConfigured
from eve_miro.paths import mirofish_root

_LOCAL_DEFAULT_URL = "http://127.0.0.1:5001"
_PLACEHOLDER_KEYS = {
    "",
    "your_api_key_here",
    "your_zep_api_key_here",
    "changeme",
}


def _env(name: str) -> str | None:
    v = os.environ.get(name, "").strip()
    return v or None


def mirofish_url() -> str:
    return (_env("MIROFISH_URL") or _LOCAL_DEFAULT_URL).rstrip("/")


def mirofish_timeout_s() -> float:
    """Default 120s (tests / mocked client). Live runs should set 3600."""
    raw = _env("MIROFISH_TIMEOUT_S")
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return 120.0


def mirofish_poll_s() -> float:
    raw = _env("MIROFISH_POLL_S")
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return 0.05


def _read_dotenv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return out
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key:
            out[key] = value
    return out


def _clean_key(value: str | None) -> str | None:
    if value is None:
        return None
    v = value.strip()
    if not v or v.lower() in _PLACEHOLDER_KEYS:
        return None
    return v


def local_memory_allowed() -> bool:
    """Skip ZEP_API_KEY for a local/dev boot. Does not fake Zep Cloud."""
    mem = (_env("MIROFISH_MEMORY") or "").strip().lower()
    if mem in {"local", "dev", "skip", "none"}:
        return True
    flag = (_env("EVE_MIRO_ALLOW_LOCAL_MEMORY") or "").strip().lower()
    return flag in {"1", "true", "yes", "on"}


def mirofish_keys() -> dict[str, str | None]:
    """LLM_API_KEY and ZEP_API_KEY from process env or ``mirofish/.env``. Never invented."""
    file_keys = _read_dotenv(mirofish_root() / ".env")
    llm = _clean_key(_env("LLM_API_KEY") or file_keys.get("LLM_API_KEY"))
    zep = _clean_key(_env("ZEP_API_KEY") or file_keys.get("ZEP_API_KEY"))
    return {"LLM_API_KEY": llm, "ZEP_API_KEY": zep}


def missing_mirofish_keys() -> list[str]:
    keys = mirofish_keys()
    missing = []
    if not keys.get("LLM_API_KEY"):
        missing.append("LLM_API_KEY")
    if not keys.get("ZEP_API_KEY") and not local_memory_allowed():
        missing.append("ZEP_API_KEY")
    return missing


def mirofish_configured() -> bool:
    """True when LLM_API_KEY is set and ZEP is set or local-memory bypass is on."""
    return not missing_mirofish_keys()


def _require_configured() -> None:
    missing = missing_mirofish_keys()
    if not missing:
        return
    parts = []
    if "LLM_API_KEY" in missing:
        parts.append(
            "LLM_API_KEY missing. Set LLM_API_KEY for an OpenAI-compatible "
            "endpoint (local GGUF http://127.0.0.1:8088/v1 dummy key 'local')."
        )
    if "ZEP_API_KEY" in missing:
        parts.append(
            "ZEP_API_KEY missing. Zep Cloud is required for graph memory, "
            "or set MIROFISH_MEMORY=local / EVE_MIRO_ALLOW_LOCAL_MEMORY=1 "
            "for a local/dev boot (does not fake Zep Cloud)."
        )
    raise EngineNotConfigured(" ".join(parts) if parts else f"MiroFish keys missing: {', '.join(missing)}")


def _unwrap(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise EngineNotConfigured(f"mirofish response is not an object: {type(payload).__name__}")
    if payload.get("success") is False:
        err = payload.get("error") or payload.get("message") or "mirofish request failed"
        raise EngineNotConfigured(str(err))
    data = payload.get("data")
    if isinstance(data, dict):
        return data
    return payload


def _server_down(exc: Exception) -> EngineNotConfigured:
    err = EngineNotConfigured(
        "mirofish server not running; python mirofish/backend/run.py"
    )
    err.__cause__ = exc
    return err


class MiroFishClient:
    """Walk the real Flask route sequence against ``MIROFISH_URL``."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout: float | None = None,
        poll_interval: float | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = (base_url or mirofish_url()).rstrip("/")
        self.timeout = float(timeout if timeout is not None else mirofish_timeout_s())
        self.poll_interval = float(poll_interval if poll_interval is not None else mirofish_poll_s())
        self._client = client

    def _url(self, path: str) -> str:
        return urljoin(self.base_url + "/", path.lstrip("/"))

    async def _request(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        url = self._url(path)
        try:
            response = await client.request(method, url, **kwargs)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.NetworkError, httpx.TimeoutException) as exc:
            raise _server_down(exc)
        if response.status_code >= 400:
            detail = response.text[:400]
            raise EngineNotConfigured(
                f"mirofish {method} {path} failed HTTP {response.status_code}: {detail}"
            )
        try:
            payload = response.json()
        except Exception as exc:
            raise EngineNotConfigured(f"mirofish {method} {path} returned non-JSON") from exc
        return _unwrap(payload)

    async def run_pipeline(
        self,
        seed_md: bytes,
        *,
        requirement: str,
        project_name: str = "eve-miro",
        max_rounds: int = 10,
        platform: str = "twitter",
        enable_twitter: bool = True,
        enable_reddit: bool = True,
        filename: str = "seed.md",
    ) -> dict[str, Any]:
        """Execute the graph→simulation sequence. Returns actions/timeline payload."""
        _require_configured()
        deadline = time.monotonic() + self.timeout
        own = self._client is None
        timeout = httpx.Timeout(self.timeout)
        client = self._client or httpx.AsyncClient(timeout=timeout, follow_redirects=True)
        try:
            files = {"files": (filename, seed_md, "text/markdown")}
            form = {
                "simulation_requirement": requirement or "Simulate synthetic statistical personas. Not real people.",
                "project_name": project_name,
            }
            ontology = await self._request(
                client, "POST", "/api/graph/ontology/generate", files=files, data=form
            )
            project_id = ontology.get("project_id")
            if not project_id:
                raise EngineNotConfigured("mirofish ontology/generate did not return project_id")

            built = await self._request(
                client, "POST", "/api/graph/build", json={"project_id": project_id}
            )
            task_id = built.get("task_id")
            if not task_id:
                raise EngineNotConfigured("mirofish graph/build did not return task_id")

            graph_id = await self._poll_graph_task(client, str(task_id), deadline)

            created = await self._request(
                client,
                "POST",
                "/api/simulation/create",
                json={
                    "project_id": project_id,
                    "graph_id": graph_id,
                    "enable_twitter": enable_twitter,
                    "enable_reddit": enable_reddit,
                },
            )
            simulation_id = created.get("simulation_id")
            if not simulation_id:
                raise EngineNotConfigured("mirofish simulation/create did not return simulation_id")

            prepared = await self._request(
                client, "POST", "/api/simulation/prepare", json={"simulation_id": simulation_id}
            )
            if not (
                prepared.get("already_prepared")
                or str(prepared.get("status") or "").lower() in {"ready", "completed"}
            ):
                prep_task = prepared.get("task_id")
                await self._poll_prepare(client, str(simulation_id), prep_task, deadline)

            await self._request(
                client,
                "POST",
                "/api/simulation/start",
                json={
                    "simulation_id": simulation_id,
                    "max_rounds": int(max_rounds),
                    "platform": platform,
                },
            )
            await self._poll_run(client, str(simulation_id), deadline)

            actions_payload = await self._request(
                client, "GET", f"/api/simulation/{simulation_id}/actions", params={"limit": 10000}
            )
            timeline_payload = await self._request(
                client, "GET", f"/api/simulation/{simulation_id}/timeline"
            )
            actions = actions_payload.get("actions") or []
            timeline = timeline_payload.get("timeline") or []
            return {
                "project_id": project_id,
                "graph_id": graph_id,
                "simulation_id": simulation_id,
                "actions": actions if isinstance(actions, list) else [],
                "timeline": timeline if isinstance(timeline, list) else [],
                "rounds_count": timeline_payload.get("rounds_count"),
            }
        finally:
            if own:
                await client.aclose()

    def _check_deadline(self, deadline: float) -> None:
        if time.monotonic() > deadline:
            raise EngineNotConfigured(
                f"mirofish timed out after {self.timeout}s (set MIROFISH_TIMEOUT_S=3600 for live runs)"
            )

    async def _sleep(self) -> None:
        import asyncio

        await asyncio.sleep(self.poll_interval)

    async def _poll_graph_task(
        self, client: httpx.AsyncClient, task_id: str, deadline: float
    ) -> str | None:
        while True:
            self._check_deadline(deadline)
            data = await self._request(client, "GET", f"/api/graph/task/{task_id}")
            status = str(data.get("status") or "").lower()
            if status in {"failed", "error"}:
                raise EngineNotConfigured(
                    f"mirofish graph task failed: {data.get('error') or data.get('message') or status}"
                )
            result = data.get("result") if isinstance(data.get("result"), dict) else {}
            graph_id = result.get("graph_id") or data.get("graph_id")
            if status in {"completed", "complete", "ready", "success"} or graph_id:
                return graph_id
            await self._sleep()

    async def _poll_prepare(
        self,
        client: httpx.AsyncClient,
        simulation_id: str,
        task_id: str | None,
        deadline: float,
    ) -> None:
        body: dict[str, Any] = {"simulation_id": simulation_id}
        if task_id:
            body["task_id"] = task_id
        while True:
            self._check_deadline(deadline)
            data = await self._request(client, "POST", "/api/simulation/prepare/status", json=body)
            status = str(data.get("status") or "").lower()
            if status in {"failed", "error"}:
                raise EngineNotConfigured(
                    f"mirofish prepare failed: {data.get('error') or data.get('message') or status}"
                )
            if (
                data.get("already_prepared")
                or status in {"ready", "completed", "complete", "success"}
                or int(data.get("progress") or 0) >= 100
            ):
                return
            await self._sleep()

    async def _poll_run(self, client: httpx.AsyncClient, simulation_id: str, deadline: float) -> None:
        while True:
            self._check_deadline(deadline)
            data = await self._request(client, "GET", f"/api/simulation/{simulation_id}/run-status")
            status = str(data.get("runner_status") or data.get("status") or "").lower()
            if status in {"failed", "error"}:
                raise EngineNotConfigured(
                    f"mirofish run failed: {data.get('error') or data.get('message') or status}"
                )
            if status in {"completed", "complete", "stopped", "success"}:
                return
            await self._sleep()


def seed_markdown_from_simulation(simulation: Simulation) -> bytes:
    """Seed .md bytes from MiroWorldAdapter snapshot or a compact WorldState-like dump."""
    snap = dict(simulation.world_snapshot or {})
    doc = snap.get("seed_document")
    if isinstance(doc, str) and doc.strip():
        body = doc.strip()
        if not body.startswith("#"):
            body = f"# MiroFish seed\n\n{body}\n"
        return body.encode("utf-8")
    lines = [
        "# MiroFish seed",
        "",
        "SIMULATED context (not an observation). Synthetic statistical personas, not real people.",
        "",
        f"- world_id: {simulation.world_id}",
        f"- scenario: {simulation.scenario_name}",
        f"- scenario_type: {simulation.scenario_type}",
        f"- information_cutoff: {iso(simulation.information_cutoff)}",
        f"- origin: {iso(simulation.origin)}",
        f"- hours: {simulation.hours}",
        f"- population_n: {simulation.population_n}",
        f"- seed: {simulation.seed}",
    ]
    weather = ((snap.get("physical_conditions") or {}).get("weather") or {}).get("latest") or {}
    if weather:
        lines.append(f"- wind_speed_10m: {weather.get('wind_speed_10m')}")
        lines.append(f"- weather_kind: {weather.get('kind')}")
    region = None
    for loc in snap.get("locations") or []:
        if isinstance(loc, dict) and loc.get("region"):
            region = loc["region"]
            break
    if region:
        lines.append(f"- region: {region}")
    lines.append("")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _map_action_kind(action_type: str) -> str:
    raw = (action_type or "stay").strip()
    lower = raw.lower()
    allowed = {"stay", "evacuate", "shelter", "stuck", "buy", "sell", "hold"}
    if lower in allowed:
        return lower
    if "evacuate" in lower:
        return "evacuate"
    if "shelter" in lower:
        return "shelter"
    if "stuck" in lower or "block" in lower:
        return "stuck"
    return "stay"


def map_mirofish_result(simulation: Simulation, payload: dict[str, Any]) -> SimulationResult:
    """Map actions/timeline into AgentAction-like traces + predicted_series. SIMULATED."""
    actions_raw = list(payload.get("actions") or [])
    timeline_raw = list(payload.get("timeline") or [])
    traces: list[dict[str, Any]] = []
    steps: list[SimulationStep] = []
    posts_by_round: dict[int, float] = {}
    origin = simulation.origin

    for row in actions_raw:
        if not isinstance(row, dict):
            continue
        round_num = int(row.get("round_num") or row.get("hour") or 0)
        action_type = str(row.get("action_type") or row.get("action") or "stay")
        agent_id = str(row.get("agent_id") if row.get("agent_id") is not None else row.get("agent_name") or "agent")
        t_raw = row.get("timestamp") or row.get("t")
        try:
            t = as_utc(t_raw) if t_raw else origin + timedelta(hours=round_num)
        except Exception:
            t = origin + timedelta(hours=round_num)
        kind = _map_action_kind(action_type)
        success = row.get("success")
        outcome = str(row.get("result") or row.get("outcome") or ("ok" if success is not False else "failed"))
        traces.append(
            {
                "simulation_id": simulation.id,
                "mirofish_simulation_id": payload.get("simulation_id"),
                "hour": round_num,
                "t": iso(t),
                "agent_id": agent_id,
                "action": action_type,
                "mapped_action": kind,
                "outcome": outcome,
                "platform": row.get("platform"),
                "provenance_kind": ProvenanceKind.SIMULATED.value,
            }
        )
        if "CREATE_POST" in action_type.upper() or "post" in action_type.lower():
            posts_by_round[round_num] = posts_by_round.get(round_num, 0.0) + 1.0

    for item in timeline_raw:
        if not isinstance(item, dict):
            continue
        round_num = int(item.get("round_num") or item.get("hour") or 0)
        t_raw = item.get("start_time") or item.get("timestamp") or item.get("t")
        try:
            t = as_utc(t_raw) if t_raw else origin + timedelta(hours=round_num)
        except Exception:
            t = origin + timedelta(hours=round_num)
        tw = float(item.get("twitter_actions") or 0)
        rd = float(item.get("reddit_actions") or 0)
        post_n = posts_by_round.get(round_num, tw + rd)
        posts_by_round[round_num] = max(posts_by_round.get(round_num, 0.0), post_n)
        step_actions: list[AgentAction] = []
        for row in item.get("actions") or []:
            if not isinstance(row, dict):
                continue
            action_type = str(row.get("action_type") or row.get("action") or "stay")
            kind = _map_action_kind(action_type)
            step_actions.append(
                AgentAction(
                    agent_id=str(row.get("agent_id") or "agent"),
                    t=t,
                    hour=round_num,
                    action=kind,  # type: ignore[arg-type]
                    wind_speed=0.0,
                    congestion=0.0,
                    warning_active=False,
                    warning_received=False,
                    outcome=str(row.get("result") or row.get("outcome") or action_type),
                    provenance_kind=ProvenanceKind.SIMULATED,
                )
            )
        steps.append(
            SimulationStep(
                hour=round_num,
                t=t,
                wind_speed=0.0,
                precipitation=0.0,
                congestion=0.0,
                warning_active=False,
                evacuated_n=int(tw),
                stuck_n=int(rd),
                actions=step_actions,
            )
        )

    rounds_sorted = sorted(posts_by_round)
    if not rounds_sorted and timeline_raw:
        rounds_sorted = list(range(len(timeline_raw)))
        for i, item in enumerate(timeline_raw):
            if isinstance(item, dict):
                posts_by_round[i] = float(
                    (item.get("twitter_actions") or 0) + (item.get("reddit_actions") or 0)
                )
    posts_series = [float(posts_by_round.get(r, 0.0)) for r in rounds_sorted]
    times = []
    for r in rounds_sorted:
        match = next((s for s in steps if s.hour == r), None)
        times.append(iso(match.t if match else origin + timedelta(hours=r)))

    simulation.status = "completed"
    simulation.provenance_kind = ProvenanceKind.SIMULATED
    if steps:
        simulation.steps = steps
        simulation.cursor_hour = steps[-1].hour + 1

    summary = {
        "hours": len(steps) or len(rounds_sorted) or simulation.hours,
        "evacuated": 0,
        "stuck": 0,
        "peak_wind": 0,
        "peak_congestion": 0,
        "posts": int(sum(posts_series)),
        "rounds": len(rounds_sorted),
        "actions_n": len(traces),
        "mirofish_simulation_id": payload.get("simulation_id"),
        "graph_id": payload.get("graph_id"),
        "project_id": payload.get("project_id"),
        "engine": "mirofish",
        "provenance_kind": ProvenanceKind.SIMULATED.value,
        "disclaimer": simulation.disclaimer,
    }
    predicted_series: dict[str, list[float]] = {}
    if posts_series:
        predicted_series["posts"] = posts_series
        predicted_series["rounds"] = [float(r) for r in rounds_sorted]
    return SimulationResult(
        simulation=simulation,
        traces=traces,
        predicted_series=predicted_series,
        predicted_times=times,
        summary=summary,
    )


async def run_mirofish_simulation(
    simulation: Simulation,
    until: datetime,
    *,
    url: str | None = None,
    timeout: float | None = None,
    client: httpx.AsyncClient | None = None,
) -> SimulationResult:
    """Fail-closed entry used by MiroFishEngine.run."""
    _require_configured()
    hours = max(1, int(simulation.hours or 1))
    try:
        remaining = (as_utc(until) - simulation.origin).total_seconds() / 3600.0
        if remaining > 0:
            hours = max(1, min(hours, int(remaining) or hours))
    except Exception:
        pass
    requirement = (
        f"Simulate scenario {simulation.scenario_name} ({simulation.scenario_type}) "
        f"for {hours} rounds with {simulation.population_n} synthetic statistical personas. "
        "Not real people. SIMULATED."
    )
    mf = MiroFishClient(base_url=url, timeout=timeout, client=client)
    try:
        payload = await mf.run_pipeline(
            seed_markdown_from_simulation(simulation),
            requirement=requirement,
            project_name=simulation.scenario_name or "eve-miro",
            max_rounds=hours,
            platform="twitter",
        )
    except EngineNotConfigured:
        raise
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.NetworkError, httpx.TimeoutException) as exc:
        raise _server_down(exc)
    mapped = map_mirofish_result(simulation, payload)
    mapped.summary["engine"] = "mirofish"
    mapped.summary["provenance_kind"] = ProvenanceKind.SIMULATED.value
    return mapped
