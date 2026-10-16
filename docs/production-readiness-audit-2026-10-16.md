# EVE-MIRO Production Readiness Audit

Date: 2026-10-16  
Scope: GitHub default branch `main`, API/provider mode selection, scenario routing, request validation, CI configuration, and operational boundaries.

## Executive summary

The repository already has meaningful safeguards: provenance types, cutoff-aware projection, loopback-oriented API defaults, CORS restrictions, fail-closed engine selection, fixture-backed tests, and separate Python/Node CI jobs. This audit does not treat the project as a blank slate.

This change fixes request-mode selection and scenario-routing correctness, adds input bounds and regression tests, and improves the CI signal. It does not make the service horizontally scalable or safe to expose publicly without authentication and persistent storage.

## Findings and disposition

### Fixed in this PR

1. **Explicit live provider requests could silently use fixtures (high).** Provider mode was selected from process-wide environment variables; `FIXTURES` defaults to enabled, and API handlers used `setdefault`, which does not override an existing value. Consequently, `use_fixtures=false` could still select fixtures. Process-wide environment mutation is also unsafe when concurrent requests want different modes. Added a `ContextVar`-based fixture override and use it around provider calls in request handlers. The override is restored after the call and does not mutate process environment.
2. **Unknown scenario IDs silently fell back to the typhoon scenario (high).** The route compared a scenario ID to the world registry and then selected the default scenario for most unknown IDs. It now resolves stored, validated scenarios or known bundled scenarios and returns a 404 for unknown IDs. Path-like IDs are rejected before lookup.
3. **Stored scenarios were not usable consistently (high).** Scenario creation stored raw dictionaries while simulation creation expected a bundled YAML scenario. Saved scenarios are now validated into the Scenario model, and the simulation route can resolve them.
4. **Duplicate world IDs silently replaced registry entries (medium).** World creation now returns HTTP 409 instead of overwriting an existing world.
5. **Simulation population had no API bound (medium).** Population is now constrained to 1–100,000 at request validation, preventing zero/negative values and accidental unbounded allocations.
6. **CI did not make the test environment explicit or retain a coverage artifact (medium).** CI now sets deterministic fixture/stub environment variables, supports manual dispatch, applies job timeouts, disables persisted checkout credentials, and publishes the coverage XML artifact.

### Remaining production risks

1. **No authentication or authorization.** CORS is not an access-control boundary. The API has mutating endpoints for worlds, ingestion, simulations, scenarios, experiments, and market runs. Keep it loopback-only unless a separately reviewed authentication/authorization layer and network policy are deployed.
2. **In-process state is not durable or multi-worker safe.** Worlds, simulations, evaluations, experiences, and results are held in application registries. A restart loses this state; multiple workers do not share it. The optional Postgres/Redis/MinIO compose services do not by themselves prove that every API registry is persisted.
3. **External engine execution needs operational isolation.** Live MiroFish/OASIS and LLM calls can be slow and expensive. Use explicit timeouts, quotas, queueing, cancellation, per-user budgets, and isolated worker processes before multi-tenant deployment.
4. **Provider health is not equivalent to application readiness.** `/health` currently reports application status plus provider health snapshots; a healthy response does not guarantee that an LLM, MiroFish service, EVE CLI, or persistent store is ready. Deployments need distinct liveness/readiness checks and a clear startup contract.
5. **Resource limits need deployment-level enforcement.** Request-body size, concurrency, per-client rate limits, and maximum live ingestion window are not comprehensively enforced by the application. Apply reverse-proxy limits and service-level budgets.
6. **Dependency risk is still being addressed in open PRs.** At audit time, dependency-hardening PRs #55 and #56 are open. Review and merge them only after their own checks and dependency resolution are verified.
7. **Release/deployment policy remains environment-specific.** This change strengthens validation CI; it does not deploy to production, publish a package, or change branch protection/secrets settings. Those require repository/environment policy and deployment credentials.

## Verification plan

- Python lint: `ruff check src tests scripts`
- Python tests: `FIXTURES=1 EVE_MIRO_ENGINES=stub LIVE=0 python -m pytest -q`
- TypeScript: `npm run typecheck` from `eve/`
- TypeScript tests: `npm test` from `eve/`
- CI retains a coverage report artifact for inspection.

The current execution environment could not clone GitHub over direct network access, and the repository named `fernandogarzaaa/testeeth` was not discoverable through the connected GitHub repository listing/search. Therefore, this audit does **not** claim a local test run or a test run inside `testeeth`; the pull request's GitHub Actions results must be checked after creation.

## Recommended next sequence

1. Review this PR and require all CI jobs to pass.
2. Merge dependency hardening PRs #55/#56 after verifying their checks.
3. Add an authentication boundary before any non-loopback exposure.
4. Persist canonical state and job status in Postgres; make worker/queue semantics explicit.
5. Add a real readiness endpoint for required dependencies, rate limits, request-size limits, and bounded live-provider windows.
6. Add scheduled dependency scanning and a reviewed, tagged release workflow once release signing, artifact retention, and rollback policy are agreed.
