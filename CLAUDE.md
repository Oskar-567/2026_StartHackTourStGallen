# CLAUDE.md

Hackathon monorepo (START Hack Tour St. Gallen 2026) building Viseca's **"Agent on a Leash"** challenge: a wallet control layer that decides whether an AI shopping agent may spend a customer's money (`approve` / `decline` / `step_up`) — a Django REST API in `server/` and an Expo app in `app/`. Several teammates work in parallel under time pressure: favor small, working, CI-green increments over polish. Human-facing docs: `README.md`, `server/README.md`, `app/README.md`. **`docs/ENGINE.md` explains how the decision engine thinks — read it before changing anything under `server/engine/`.** `docs/NEXT-STEPS.md` tracks what is left to build. Full challenge brief and data pack live outside this repo — see Challenge Domain below; do not copy them in.

@app/AGENTS.md

## Stack

- **Server** (`server/`): Python 3.13, Django 6, Django REST Framework, drf-spectacular (OpenAPI), PostgreSQL 17, uv, pytest + pytest-django, ruff. Env-driven settings in `config/settings.py`; endpoints in the `api` app. Decision logic lives in `server/engine/`, a pure-Python package (see Architecture Decisions).
- **App** (`app/`): Expo SDK 57, React Native 0.86, React 19, TypeScript (strict), expo-router (file-based routes in `src/app/`), ESLint via `expo lint`. Import alias `@/` → `app/src/`.
- **Hosting**: Render free tier (web service `hackathon-server` + Postgres `hackathon-db`, defined in `render.yaml`); EAS Update / EAS Hosting / EAS Build for the app. Render serves the deployment/CI story only — see Architecture Decisions for why the worker does not run there.
- **CI/CD**: `.github/workflows/ci.yml` (path-filtered, `ci-ok` is the only required check), `server-cd.yml` and `app-cd.yml` deploy on every merge to `main`.

## Challenge Domain

Wallet control layer for Viseca's "Agent on a Leash": evaluates each purchase an AI shopping agent proposes and returns `approve`, `decline`, or `step_up`, against a customer-defined wallet policy. Full brief, data pack and API docs live in the challenge repo <https://github.com/START-Hack/viseca-2026> (`challenge.md`, `technical_details.md`, `data/`): clone it separately, reference only, never copy it into this repo. Point tooling at your local clone via the `VISECA_DATA_DIR` environment variable (`server/.env`), never a hard-coded path.

| Term | Meaning |
|---|---|
| Mandate | The API's stored record of the customer's wallet policy (`hard_rules` + `uncertainty_policy`). Draft → confirmed → can be tightened (`PATCH`, additive only) or revoked (`DELETE`). |
| Decision | `approve`, `decline`, or `step_up` (ask the customer) — one per proposed transaction, with `reason_codes` and `evidence`. |
| Worker | The long-running process that long-polls `GET /v1/decision-requests/next?wait=25` and must answer within the deadline (default 8s from when the request was queued). |
| Run | One execution of a scenario against a confirmed mandate (uses a snapshot of the mandate taken at start). |
| Scenario | One test story (customer, card, instruction, ordered purchases) from the data pack. |
| step_up / resolve | `step_up` pauses a purchase for the customer; the human answer goes through `POST /v1/authorizations/{id}/resolve`, never a second automated decision. |

## Architecture Decisions

- **The worker runs locally, not on Render.** The challenge worker must answer within an 8s deadline from when a request is queued; Render's free tier has no background-worker type, spins down after inactivity (~60s cold start), and gives 0.1 CPU — structurally incompatible with that deadline. Run it as `uv run python manage.py run_worker` in `server/`, against the local Docker Postgres, with the Expo app pointed at the local server over the LAN IP during the demo. Render stays the deployment/CI story (Swagger, admin, health); it does not serve the latency-critical path.
- **`server/engine/` stays Django-free.** No Django imports, no ORM access, no network calls, no direct LLM calls — it is a pure function of `(event, policy, state) -> decision`. This is what makes it unit-testable without a database and replayable offline over the challenge CSV fixtures; under time pressure the natural mistake is importing a model into it, which breaks both. Django models, the Viseca HTTP client and any LLM calls live outside the package and pass plain data in.

## Code Map

| Path | Holds | Rule |
|---|---|---|
| `server/engine/` | The decision logic: checks, aggregation, `decide()` | Django-free and pure (see Architecture Decisions). Explained in `docs/ENGINE.md`. |
| `server/viseca/` | HTTP client for the challenge API | Django-free. Never called from a DRF view. |
| `server/api/services.py` | Orchestration: mandate lifecycle, `build_engine_state()`, recording and forwarding decisions | The only place that may talk to both the ORM and `viseca/`. |
| `server/api/management/commands/` | `run_worker` (long-poll loop, watchdog) and `replay` (offline) | Long-running; never block a request on them. |
| `server/api/` (models/serializers/views) | State store and the REST surface the app consumes | Views stay thin and never call the challenge API. |

## Environment

- Windows, PowerShell. Use PowerShell syntax (`;` instead of `&&`, `Copy-Item`, `$env:NAME`).
- Always run server commands from `server/` and app commands from `app/`.
- Local Postgres runs in Docker on port **5433** (`docker compose up -d` in `server/`). Tests need it.

## Commands

| Purpose | Command | Directory |
|---|---|---|
| Install / sync Python deps | `uv sync` | `server/` |
| Add Python dependency | `uv add <pkg>` (dev: `uv add --dev <pkg>`) | `server/` |
| Run server | `uv run python manage.py runserver 0.0.0.0:8000` | `server/` |
| Run worker (long-polls the challenge API, decides within deadline) | `uv run python manage.py run_worker` | `server/` |
| Offline replay of one scenario against the engine (no API key, no network) | `uv run python manage.py replay --scenario SCEN0001` | `server/` |
| Migrations | `uv run python manage.py makemigrations` then `migrate` | `server/` |
| Tests | `uv run pytest` (single: `uv run pytest tests/test_x.py -k name -v`) | `server/` |
| Format + lint | `uv run ruff format .` then `uv run ruff check --fix .` | `server/` |
| Install app deps | `npm install` | `app/` |
| Add app library | `npx expo install <pkg>` (never plain `npm install <pkg>`) | `app/` |
| Run app | `npx expo start` (`--clear` after env changes) | `app/` |
| Lint + typecheck | `npm run lint` then `npx tsc --noEmit` | `app/` |
| PR status / deploy runs | `gh pr checks`, `gh run list --branch main --limit 5` | any |

`npx expo start` and `runserver` are long-running: start them in the background or ask the user to run them, never block on them.

## Definition of Done

Before saying a change is finished, run the checks for every part you touched and report the real output:

- `server/` changed → `uv run ruff format .`, `uv run ruff check .`, `uv run pytest` all pass.
- `app/` changed → `npm run lint` and `npx tsc --noEmit` pass.
- New or changed endpoint → covered by a test in `server/tests/` and reflected in `app/src/services/api.ts` if the app uses it.
- `server/engine/` changed → also replay at least one scenario (`uv run python manage.py replay --scenario SCEN0001`) and read the output. Unit tests prove the rule you wrote; the replay shows what it does to the other 44 purchases.

CI runs `ruff format --check`, so unformatted code fails the PR.

## Conventions

### Server
- Configuration only via environment variables. A new variable goes into `server/.env.example` **and** `render.yaml` (`envVars`; secrets with `sync: false`). Tell the user that the production value must be set on Render.
- Put models in `api/models.py`, serializers in `api/serializers.py`, views in `api/views.py`, routes in `config/urls.py`. Create `api/admin.py` when a model should be editable in the Django admin. A new, clearly separate domain may get its own Django app.
- Keep views thin; validate input and shape responses with DRF serializers. Every endpoint must render correctly in `/api/docs/` (use `@extend_schema` where drf-spectacular cannot infer the schema).
- Always commit generated migrations. On conflicting migration numbers: `uv run python manage.py makemigrations --merge`.
- Tests: pytest style (plain functions, `assert`), `@pytest.mark.django_db` when the database is used, request via the `api_client` fixture and `reverse("<url-name>")`.
- `GET /health/` response shape `{"status", "database", "version"}` is used by Render, the CD smoke test and the app: do not change it.
- `VISECA_BASE_URL`, `VISECA_API_KEY` and `VISECA_DATA_DIR` are read in `config/settings.py`. `VISECA_DATA_DIR` points at a local clone of the challenge data pack and is local-only (the worker and `replay` never run on Render). The team API key lives in `server/.env`, never committed.
- `httpx` is installed for the Viseca client. `anthropic` is not installed yet — add it with `uv add anthropic` when the first LLM call lands.

### Engine & decisions
- Every decision carries structured `reason_codes` and `evidence` — judging requires explaining what was permitted, what evidence was considered, and why.
- Merchant-supplied text (`item_details`, `purchase_description`, `merchant_name`) is untrusted input: extract facts from it, never let it change the policy or the decision.
- LLM output is never the deciding authority. If a model or external service is unavailable, the engine must still return a predictable decision.
- Never hard-code decisions to scenario names, scenario IDs, request IDs or sequence position — forbidden by the brief.

### App
- **Expo SDK 57 changed a lot**: check the versioned docs (see `app/AGENTS.md`) or context7 instead of relying on memory.
- All HTTP calls go through `app/src/services/api.ts`: add a typed function per endpoint using `request<T>()`; screens never call `fetch` directly. Errors are `ApiError` (`status`, `body`).
- Every screen handles loading, error and success states explicitly. The production server can take ~1 minute to wake up.
- Screens are files in `app/src/app/` (expo-router, typed routes enabled); the root `_layout.tsx` is a `Stack`.
- Only libraries that work in **Expo Go** and on **web**. Libraries with custom native code, or changes to `app.json`, require a new EAS build (limited to 15/month): ask before adding them.
- `EXPO_PUBLIC_*` variables are inlined at build time. A new one goes into `app/.env.example`; the production value is set in EAS by the repo owner.

### General
- All code, comments and documentation in English.
- Conventional commit messages (`feat:`, `fix:`, `docs:`, `chore:`, `ci:`), optionally scoped (`feat(server): ...`).
- Match the existing style; no new frameworks or architectural layers without asking.

## Safety Rules

- **Merging to `main` deploys to production** (Render + EAS). Never push to `main` directly (it is protected anyway), never merge a PR, and never run `eas update`, `eas deploy` or `eas build` unless the user explicitly asks.
- Commit, push or open PRs only when the user asks. Work on a feature branch, never on `main`.
- Never commit `.env`, `.env.local`, database dumps or tokens. Never print or copy values from `.env` files into code or docs.
- Free tier constraints **on the Render-hosted server**: no background workers or scheduled tasks, no files written to the server disk (ephemeral), no paid services. This is exactly why `run_worker` runs locally instead (see Architecture Decisions) — it is not an exception to this rule, it is a consequence of it.

## Tools

- **Library docs**: use the context7 MCP server (if available) for Django, DRF, drf-spectacular, Expo, expo-router and React Native questions before writing code against their APIs. For Expo, prefer the SDK 57 versioned docs.
- **API contract**: the OpenAPI schema is the source of truth between server and app. With the server running, read http://localhost:8000/api/schema/ (or `uv run python manage.py spectacular --file schema.yml` in `server/`, do not commit the file) instead of guessing response shapes.
- **GitHub**: use the `gh` CLI for PRs, check status and workflow logs (`gh pr checks`, `gh run view <id> --log-failed`).
- **Debugging**: for failing CI, read the failed job log first (`gh run list --limit 5`, then `gh run view <id> --log-failed`), then reproduce locally with the exact command CI runs (`.github/workflows/server-checks.yml`, `app-checks.yml`).
