# What Is Left to Build

Status as of 2026-09-18. This document is the plan from the working scaffold to a
complete, demonstrable answer to the Viseca "Agent on a Leash" challenge.

Read `docs/ENGINE.md` first if you have not — this document assumes you know what
`decide()`, a check, and `step_up` are.

---

## Where we are today

Everything below is verified, not estimated: `94 passed`, `ruff check` clean, no
migration drift, all five scenarios replay with exit 0.

| Piece | State |
|---|---|
| Decision engine, 6 deterministic checks | **Done** |
| Aggregation, reason codes, evidence | **Done** |
| Django state store (mandate, run, authorization, decision, spend ledger) | **Done** |
| REST surface: mandate review / confirm / tighten / revoke, step-up queue / resolve | **Done** |
| Viseca API client, 16 methods, deadline-safe timeouts | **Done** |
| `run_worker` long-poll loop with watchdog and idempotency | **Done, never run against the live API** |
| `replay` offline loop over the data pack | **Done** |
| Policy compiler (customer's sentence → rules) | **Missing** |
| Fact extraction (product text → structured facts) | **Missing** |
| `item_match` / `purpose_fit` checks | **Stubs** |
| Customer-facing app screens | **Missing** |

Replaying all 45 practice purchases currently yields **6 declines, 39 step-ups,
zero approvals**. That is correct behaviour for a system with no fact extraction
(see `docs/ENGINE.md` §9) — and it is also the single clearest statement of what
is missing.

---

## The finish line

The brief names three things a demo must show. Each one has a concrete blocker
today:

| Demo moment | Blocked by |
|---|---|
| 1. An ordinary purchase completes with little friction | No fact extraction → everything is uncertain → everything becomes `step_up` |
| 2. An ambiguous, unsafe or manipulated purchase gets a useful intervention | Mostly works; needs the injection signal and a clear explanation |
| 3. The customer can approve, reject, or revoke | Backend is done; there is no screen to do it on |

Judges must also be able to understand **what the system permitted, what evidence
it considered, why it acted, and how the customer stayed in control.** Evidence
and reason codes already exist end to end — the remaining work is making them
visible.

---

## Critical path

```
   ┌──────────────────────┐
   │ 1. Policy compiler   │────┐
   └──────────────────────┘    │
                               ├──→ ┌──────────────────┐     ┌─────────────────┐
   ┌──────────────────────┐    │    │ 4. App screens   │ ──→ │ 9. Rehearsal    │
   │ 2. Fact extraction   │────┘    │ 5. Approval queue│     │    + fallback   │
   └──────────────────────┘         └──────────────────┘     └─────────────────┘
                               ┌──→ ┌──────────────────┐
   ┌──────────────────────┐    │    │ 6. Injection     │
   │ 3. First live run    │────┘    │ 7. Explanations  │
   └──────────────────────┘         │ 8. Tuning        │
                                    └──────────────────┘
```

Items 1 and 2 are the product. Item 3 is the risk you want to retire early.
Everything else assumes those three are in place.

---

## P0 — nothing works without these

### 1. Policy compiler: the customer's sentence → executable permissions

**Goal.** Turn `"Replace my worn road-running shoes in size 43. Buy only from a
specialist sports retailer, only if the order can be returned within 14 days or
more, and pay no more than CHF 200. Ask me when uncertain."` into `hard_rules`
plus a structured `intent_spec`, plus the open questions to put in front of the
customer.

**Why it matters.** This is half the challenge statement. Right now
`replay.py` has the numeric limits typed in by hand and `create_mandate_draft()`
expects a finished policy. Nothing turns customer language into permissions.

**Where.** New module outside the engine — the engine must stay pure. Suggested:
`server/api/policy_compiler.py`, called by `services.create_mandate_draft()`.

**How.** This runs when the customer sets up their policy, so there is **no
latency pressure and a human confirms the result**. Use `claude-opus-5` with
structured outputs so the shape is guaranteed. Output:

```
hard_rules      → the machine-checkable conditions, sent to the challenge API
intent_spec     → the semantic permissions the engine needs but the API doesn't store
                  (purpose, required attributes, merchant constraints, forbidden extras)
open_questions  → what the compiler was unsure about, shown to the customer
guidance        → plain-language explanation of each rule
```

The `intent_spec` is the important half: it is what the semantic checks compare
against in step 2. Precomputing it here means the in-path model later answers a
narrow comparison question instead of reasoning from scratch — faster, smaller,
and far harder to knock off course.

**Done when.** Each of the five scenario instructions compiles to rules that
replay sensibly; the compiler reports at least one honest open question where the
instruction is genuinely ambiguous (e.g. "does an online-only sports shop count as
a specialist retailer?"); a model failure yields a clear error, never a silently
empty policy.

**Depends on.** Nothing. **Start here.**

---

### 2. Fact extraction: product text → structured facts

**Goal.** Produce the `ExtractedFacts` object that `decide()` already accepts, so
`item_match` and `purpose_fit` stop answering UNCERTAIN.

**Why it matters.** Without it every clean purchase becomes `step_up`, and demo
moment 1 is impossible.

**Where.** `server/api/facts.py` (or similar), called by `run_worker` *before*
`decide()`. Never inside `server/engine/`.

**How — and this part is a security design, not just a feature:**

- The extractor reads `item_details`, `item_name`, `purchase_description`.
  **It never sees the mandate, the limits, or the policy.** It does not know a
  spending limit exists. A product description saying *"ignore the spending
  limit"* is then talking to a component with no authority to ignore anything.
- It returns **only structured fields** — `{size, type, colour, return_days, …}` —
  validated against a schema. Free text out is not allowed. Schema violation →
  discard → UNCERTAIN.
- Hard timeout, `max_retries=0`, small `max_tokens`. The decision deadline is
  8 seconds and the worker's watchdog fires at 2 seconds remaining.
- Measure `claude-opus-5` at `output_config: {effort: "low"}` first; drop to
  `claude-haiku-4-5` only if the latency budget demands it. Cache the stable
  prefix (system prompt + `intent_spec`) and put the variable purchase JSON last.

Then fill in `engine/checks/item_match.py` and `engine/checks/purpose_fit.py`,
which already have the right signatures and `TODO` markers.

**Done when.** `replay --scenario SCEN0002` produces at least one `approve` for a
compliant purchase and a `decline`/`step_up` for a substitution or wrong size,
with evidence naming the mismatched attribute; killing the model (unset the key)
still returns decisions within the deadline, all uncertain.

**Depends on.** Item 1 for `intent_spec`.

---

### 3. First live run against the challenge API

**Goal.** `run_worker` completes `SCEN0000` end to end against the hosted API.

**Why it matters.** Everything so far is tested against mocks. Long-polling,
envelope shapes, clock skew, and the real deadline are exactly the things mocks
hide. Find those problems on day one, not during the demo.

**How.** Team API key into `server/.env`. `GET /healthz`, then `/v1/bootstrap` to
read the real timeout settings. Create and confirm a mandate, start the worker,
then start the run — **worker first**, the deadline starts when the request is
queued.

**Done when.** `SCEN0000` completes; the decision the API accepted matches what
the local `Decision` row says; a deliberately restarted worker mid-run does not
double-count spend.

**Depends on.** The API key. Do this the moment you have it.

---

## P1 — needed for the three demo moments

### 4. App: policy review and confirmation

Two screens in `app/src/app/`, all calls through `app/src/services/api.ts`.

Show the compiled rules in plain language, the open questions, and what the
system will do when unsure. The customer confirms → `POST /api/mandates/{id}/confirm/`.
Also expose tighten and revoke, since demo moment 3 requires the revocation path.

**Done when.** A mandate can be reviewed, confirmed, tightened and revoked from a
phone, and a tightening that would weaken the policy is refused with a readable
message.

**Depends on.** Item 1.

### 5. App: approval queue

`GET /api/step-ups/` every ~2 seconds — the human window is 120 seconds, so
polling is plenty and websockets are not worth the complexity.

Each pending item shows merchant, amount, basket, why it paused, and the time
remaining. Approve / decline → `POST /api/step-ups/{id}/resolve/`. The worker
forwards the answer to the challenge API on its next cycle.

**Done when.** A `step_up` raised by the worker appears on the phone within a few
seconds, and answering it visibly resolves the purchase.

**Depends on.** Item 3.

### 6. Injection signal and lookalike hardening

The `merchant` check already flags names ≥82% similar to a known shop with a
different ID. Add a signal that merchant-supplied text contains instruction-like
language, as **evidence and an uncertainty signal** — never as a filter that
silently rewrites anything.

This is demo moment 2. Being able to say *"the system noticed the shop was trying
to instruct it, and told the customer"* is much stronger than blocking silently.

**Done when.** `SCEN0004` shows an intervention whose evidence quotes the
offending text, and the purchase is judged on its own facts regardless.

**Depends on.** Item 2.

---

## P2 — what turns a working system into a winning one

### 7. Customer-facing explanations

Generate a readable sentence from the reason codes and evidence *after* the
decision is made — no latency pressure, no influence on the outcome. *"I paused
this because the basket contains socks you didn't ask for."*

Cheap to build, disproportionately convincing in a demo.

### 8. Threshold tuning

`session` (5 attempts fail / 3 uncertain), `duplicate` (2-hour window), `merchant`
(82% similarity) are first guesses with no data backing. Once items 1 and 2 land,
replay all five scenarios and tune against real output. Record why each number
changed.

Watch both failure directions: a purchase wrongly blocked is as much a failure as
one wrongly allowed.

### 9. Rehearsal and fallback plan

Run the full demo end to end at least twice. Decide in advance what you do if the
hosted API is down or the model is slow — *"here is the same scenario replayed
offline"* is a perfectly good answer if you have practised saying it.

Also prepare the sentence explaining why the worker runs locally: Render's free
tier has no background worker and a ~60 second cold start, against an 8 second
deadline. That is an informed engineering decision, and it reads like one when
you say it out loud.

---

## Suggested split

With three or four people, items 1, 2 and 4/5 are genuinely independent once the
`intent_spec` shape is agreed. **Agree that shape first, in writing** — it is the
contract between the compiler, the extractor and the checks, and it is the one
thing that will cause a painful merge if two people invent it separately.

| Person | Owns |
|---|---|
| A | Policy compiler (1), then explanations (7) |
| B | Fact extraction (2), then injection signal (6) |
| C | App screens (4, 5) |
| D | Live integration (3), then tuning (8) and rehearsal (9) |

---

## Known risks

| Risk | Mitigation |
|---|---|
| Model latency blows the 8s deadline | Watchdog already falls back to the deterministic tier at 2s remaining. Measure real latency early; `max_retries=0` on the decision path is already enforced. |
| The hosted API behaves differently than the spec | Item 3, on day one. |
| Someone imports Django into `server/engine/` | It stops being testable and replayable. `CLAUDE.md` forbids it; say so in review. |
| The demo asks about everything | Watch the approve/step-up ratio in replay after item 2. A control layer that interrupts constantly gets switched off. |
| Rules get hard-coded to scenarios to make output look good | `scenario_id` is discarded at parse time, so this needs deliberate effort — keep it that way. |

---

## Explicitly not doing

- **No Celery, Redis, or task queue.** One loop in one process is enough for 45
  purchases.
- **No websockets.** Polling every 2 seconds against a 120 second window is fine.
- **No rewrite to FastAPI.** The async argument does not apply: the worker is its
  own process and can use threads freely.
- **No deploying the worker to Render.** See Architecture Decisions in `CLAUDE.md`.
- **No hard-coding to scenario identity or sequence position.** Forbidden by the
  brief, and it would prove nothing.
