# CLAUDE.md

Hackathon monorepo (START Hack Tour St. Gallen 2026): a Django REST API in `server/` and an Expo app in `app/`. Several teammates work in parallel under time pressure: favor small, working, CI-green increments over polish. Human-facing docs: `README.md`, `server/README.md`, `app/README.md`.

@app/AGENTS.md

## Stack

- **Server** (`server/`): Python 3.13, Django 6, Django REST Framework, drf-spectacular (OpenAPI), PostgreSQL 17, uv, pytest + pytest-django, ruff. Env-driven settings in `config/settings.py`; endpoints in the `api` app.
- **App** (`app/`): Expo SDK 57, React Native 0.86, React 19, TypeScript (strict), expo-router (file-based routes in `src/app/`), ESLint via `expo lint`. Import alias `@/` → `app/src/`.
- **Hosting**: Render free tier (web service `hackathon-server` + Postgres `hackathon-db`, defined in `render.yaml`); EAS Update / EAS Hosting / EAS Build for the app.
- **CI/CD**: `.github/workflows/ci.yml` (path-filtered, `ci-ok` is the only required check), `server-cd.yml` and `app-cd.yml` deploy on every merge to `main`.

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

CI runs `ruff format --check`, so unformatted code fails the PR.

## Conventions

### Server
- Configuration only via environment variables. A new variable goes into `server/.env.example` **and** `render.yaml` (`envVars`; secrets with `sync: false`). Tell the user that the production value must be set on Render.
- Put models in `api/models.py`, serializers in `api/serializers.py`, views in `api/views.py`, routes in `config/urls.py`. Create `api/admin.py` when a model should be editable in the Django admin. A new, clearly separate domain may get its own Django app.
- Keep views thin; validate input and shape responses with DRF serializers. Every endpoint must render correctly in `/api/docs/` (use `@extend_schema` where drf-spectacular cannot infer the schema).
- Always commit generated migrations. On conflicting migration numbers: `uv run python manage.py makemigrations --merge`.
- Tests: pytest style (plain functions, `assert`), `@pytest.mark.django_db` when the database is used, request via the `api_client` fixture and `reverse("<url-name>")`.
- `GET /health/` response shape `{"status", "database", "version"}` is used by Render, the CD smoke test and the app: do not change it.

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
- Free tier constraints: no background workers or scheduled tasks on the server, no files written to the server disk (ephemeral), no paid services.

## Tools

- **Library docs**: use the context7 MCP server (if available) for Django, DRF, drf-spectacular, Expo, expo-router and React Native questions before writing code against their APIs. For Expo, prefer the SDK 57 versioned docs.
- **API contract**: the OpenAPI schema is the source of truth between server and app. With the server running, read http://localhost:8000/api/schema/ (or `uv run python manage.py spectacular --file schema.yml` in `server/`, do not commit the file) instead of guessing response shapes.
- **GitHub**: use the `gh` CLI for PRs, check status and workflow logs (`gh pr checks`, `gh run view <id> --log-failed`).
- **Debugging**: for failing CI, read the failed job log first (`gh run list --limit 5`, then `gh run view <id> --log-failed`), then reproduce locally with the exact command CI runs (`.github/workflows/server-checks.yml`, `app-checks.yml`).
