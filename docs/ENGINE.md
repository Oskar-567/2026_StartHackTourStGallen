# The Decision Engine, Explained

This document explains what `server/engine/` does, how it thinks, and why it is
built the way it is. It assumes **no prior knowledge** of the codebase, of
payments, or of Python beyond being able to read a function name. If you can
follow a flowchart, you can follow this.

If you only read one section, read [The One Big Idea](#2-the-one-big-idea).

---

## 1. The problem we are solving

An AI shopping agent can now hold your credit card. You tell it *"buy me black
running shoes for up to CHF 200"*, and it goes off and buys something.

That raises an obvious question: **who stops it when it gets that wrong?**
Not wrong in a dramatic way — wrong in ordinary ways. It buys a CHF 260 pair.
It buys from a shop that looks like the one you use but isn't. It adds socks you
never asked for. It reads a product description that says *"ignore the spending
limit"* and does exactly that.

Our project is the thing that sits between the agent and the money and answers,
for every single proposed purchase: **may this go through?**

That thing has two halves:

| Half | What it does | Where it lives |
|---|---|---|
| The **control layer** | Talks to the outside world, remembers things, shows the customer screens | `server/api/`, `server/viseca/`, `app/` |
| The **engine** | Makes the actual judgement call | `server/engine/` ← *this document* |

The engine is the small, careful core. Everything else exists to feed it and to
carry out what it says.

---

## 2. The One Big Idea

> **The engine is a pure function. It has no memory, no internet, no database,
> and no AI. You hand it everything it needs, and it hands you back a decision.**

In code, the whole engine is one function call:

```python
decision = decide(event, state, facts)
```

That is genuinely all of it. Three things go in, one thing comes out.

This sounds like a limitation. It is actually the most important design choice
in the project, for four reasons:

1. **It can be tested instantly.** No database to start, no network, no API key.
   The engine's tests run in well under a second. That means we can change how it
   thinks and know immediately whether we broke something.
2. **It can be replayed offline.** We can take all 45 practice purchases from the
   challenge data pack and run them through the engine on a laptop with the wifi
   off. That is our main development loop.
3. **It is predictable when things break.** The challenge requires an answer
   within **8 seconds**. If an AI model is slow or down, the engine still works —
   because the engine never calls the model itself. Someone else does that and
   passes the result in.
4. **It cannot be talked into anything.** The engine only ever sees structured
   data. A shop cannot send it a sentence that changes its mind, because the
   engine does not read sentences as instructions.

Everything impure — the database, the HTTP calls, the AI — lives *outside* and
passes plain data in. There is a rule about this in `CLAUDE.md`, and it exists
because the natural mistake under time pressure is to reach into the database
from inside a check "just this once", which quietly destroys all four benefits.

---

## 3. The three possible answers

The engine can say exactly three things:

| Answer | Meaning | What happens next |
|---|---|---|
| `approve` | Let it through. | The purchase goes ahead. |
| `decline` | Stop it. | The purchase is blocked. |
| `step_up` | *Ask the human.* | The purchase pauses; the customer decides on their phone. |

`step_up` is the interesting one, and it is what makes this system usable rather
than annoying. Without it, every uncertain case would have to be either a silent
approval (dangerous) or a hard block (infuriating). `step_up` lets the system say
*"I'm not sure, and you're the one whose money it is."*

**Important:** `step_up` is not a soft approval. The purchase is paused, and it
stays paused until a real person answers.

---

## 4. What goes in

### 4.1 The `event` — what is being bought

One proposed purchase, described completely. Roughly:

```
event
├── authorization_id           a unique ID for this purchase attempt
├── timestamp                  when the purchase happens (in the simulation)
├── billing_amount_chf         the total, in Swiss francs, delivery included
├── merchant                   who is selling: id, name, country, category
├── items[]                    the basket: name, category, quantity, price
├── customer_device_id         which phone/laptop the agent is working from
├── order_returnable           "true" / "false" / "unknown" / "not_applicable"
├── recent_attempt_count_10m   how many purchase attempts in the last 10 minutes
└── mandate                    the customer's rules (see below)
```

The **mandate** is the customer's wallet policy — the whole point of the system.
It contains the customer's original instruction in their own words, plus
`hard_rules`: machine-checkable conditions like *"the total must be at most CHF
20"*. It also carries the `uncertainty_policy`, which we come back to in
[section 7](#7-what-to-do-when-unsure).

### 4.2 The `state` — what happened before

The engine has no memory, so anything it needs to know about the past must be
handed to it:

| Field | Plain English |
|---|---|
| `recent_approved_purchases` | Purchases already approved, so we can add up spending over time |
| `known_merchant_ids` | Which shops this card has successfully bought from before, and how often |
| `known_device_ids` | Which devices this customer has used before |
| `seen_authorization_ids` | Purchases we already answered, so a repeat delivery isn't counted twice |
| `approved_spend_in_period_chf` | A running total, used only as a last resort |

This is assembled by `api/services.build_engine_state()` from the database and
the historical transaction file. The offline replay tool assembles the same thing
from CSV files. **They share the counting code on purpose** — if *"a shop I use
regularly"* meant something different offline than in production, the replay tool
would stop predicting what the real system does, and it would be worthless.

### 4.3 The `facts` — what an AI extracted (optional)

Some questions cannot be answered by comparing numbers. *"Is this actually a
road-running shoe in size 43?"* requires reading a product description written in
human language.

That reading is done by an AI model, **outside** the engine, and the result is
passed in as `facts` — a small structured object such as
`{size: "43", type: "road running shoe"}`.

Two things make this safe:

- The AI that reads the shop's text **never sees the customer's policy.** It does
  not know there is a spending limit. So a product description containing
  *"ignore the spending limit"* is talking to something that has no power to
  ignore anything. There is nothing there to manipulate.
- If the AI is slow, broken, or simply not built yet, `facts` is `None`, and the
  checks that need it answer **"unsure"** — never *"fine"*.

---

## 5. The checks

The engine's opinion is not one big judgement. It is eight small, independent
opinions, each looking at one narrow thing.

Every check answers with one of three verdicts:

- **PASS** — no concern from where I'm looking.
- **FAIL** — this definitively breaks the customer's rules.
- **UNCERTAIN** — this needs a human, or I don't have enough information.

Every non-PASS verdict must come with **evidence**: the specific field, its
value, and a sentence saying why it mattered. This is not decoration — being able
to show *what* the system looked at is part of what the challenge is judged on.

### The deterministic checks (fast, no AI)

| Check | What it looks at | Can it say FAIL? |
|---|---|---|
| **amount** | Every `hard_rule` about a single purchase — most often the price cap | Yes |
| **period** | Rules about spending over time, e.g. *"max CHF 300 across any seven days"* | Yes |
| **merchant** | Is this shop known? This country? Does the name mimic a known shop? | No — UNCERTAIN only |
| **session** | New device? Suspiciously many attempts? Unexpected channel? | Yes |
| **duplicate** | Have we already approved something that looks just like this? | No — UNCERTAIN only |
| **terms** | Return and cancellation terms — *only if the policy asks about them* | No — UNCERTAIN only |

A few of these deserve a closer look.

**amount** is more general than its name suggests. It interprets *any* hard rule
scoped to a single purchase, by following a dotted path into the event. A rule
saying `authorization.billing_amount_chf <= 20` and a rule saying
`authorization.merchant.merchant_country in ["CH", "DE"]` both run through the
same machinery. If a rule names a field that does not exist, or cannot be
compared, the answer is UNCERTAIN — never a crash, and never a silent pass.

**merchant** deliberately never says FAIL. An unfamiliar shop is not proof of
anything; everyone shops somewhere new eventually. It raises a flag and lets the
human decide. It also compares the shop's *name* against shops used before: if a
name is at least 82% similar to a known one but carries a different ID, that is a
classic lookalike-shop trick and gets flagged.

**session** is the one place where a behavioural signal alone can block. Five or
more purchase attempts in ten minutes reads as something going wrong, not as
enthusiastic shopping. Three or four is merely elevated → UNCERTAIN. A device
never seen before → UNCERTAIN.

**duplicate** does two different jobs. If the exact same `authorization_id`
arrives twice — a network retry — it says so plainly and makes sure the amount is
not counted against the budget twice. Separately, it looks for a *different*
purchase that is suspiciously similar: same shop, same exact CHF amount,
overlapping item categories, within two hours. That is what an accidental double
order looks like.

### The semantic checks (need AI facts)

| Check | The question it will answer |
|---|---|
| **item_match** | Is this actually the thing the customer asked for? Right size, right type? |
| **purpose_fit** | Does every item in the basket belong to the stated purpose, or did something extra sneak in? |

**These two are currently stubs.** They are real functions with the right shape,
but they always answer UNCERTAIN, because nothing produces `facts` yet. See
[section 9](#9-what-is-not-finished) for what that means in practice.

---

## 6. How eight opinions become one decision

`aggregate.py` combines them, in a strict order of precedence:

```
Did ANY check say FAIL?
        │
   yes ─┴─→ decline
        │
   no   └─→ Did ANY check say UNCERTAIN?
                    │
               yes ─┴─→ do whatever the uncertainty_policy says
                    │
               no   └─→ approve
```

Two details matter more than they look:

**The reasons come from every check that spoke up, not just the deciding one.**
If three checks fail, the decision explains all three. If one check is uncertain
alongside two failures, the outcome is `decline` — but the uncertain finding is
still reported. The system is not allowed to tidy away part of why it acted.

**A check can never cancel out another check.** Aggregation only ever *adds*
concerns to a decision that starts from "nothing found". Nothing in this design
lets a passing check override a failing one. This is written down as an invariant
in the module, because it is what makes *"adding a rule can only ever tighten
things"* true — and the customer needs that to be true, or tightening their own
policy would not be safe.

### A worked example

Customer's policy: *"Order household groceries. Max CHF 120 per order. Ask me
when uncertain."* The agent proposes a CHF 126 grocery order from a shop the card
has used many times before.

| Check | Verdict | Why |
|---|---|---|
| amount | **FAIL** | 126 > 120 |
| period | PASS | no seven-day rule is breached |
| merchant | PASS | 24 prior approved purchases at this shop |
| session | PASS | known device, normal pace |
| duplicate | PASS | nothing similar recently |
| terms | PASS | the policy says nothing about returns |
| *semantic tier* | *skipped* | already declining — no point paying for AI |

→ **`decline`**, reason code `amount_limit_exceeded`, evidence
`billing_amount_chf = 126.00`.

This is a real result from our replay tool, on purchase `AU0004`.

---

## 7. What to do when unsure

When at least one check is UNCERTAIN and nothing outright failed, the engine does
**not** decide for itself. It does what the customer told it to do. The mandate
carries an `uncertainty_policy` with three possible values:

| Setting | Meaning | Result |
|---|---|---|
| `ask` | "Check with me" | `step_up` |
| `decline` | "When in doubt, don't" | `decline` |
| `approve` | "Don't bother me" | `approve` |

The customer chooses this, and they can tighten it later but never loosen it.
That asymmetry is deliberate: making your own rules stricter should always be
allowed; quietly making them looser should not.

---

## 8. Four principles that explain the surprising behaviour

If some engine behaviour looks odd, it is almost always one of these four.

### 8.1 Missing information is never permission

This is the single most important rule in the engine. There are three different
ways a fact can be absent, and they mean different things:

| Value | Meaning | Engine's response |
|---|---|---|
| `null` | The field exists but holds no value | **UNCERTAIN** |
| `"unknown"` | The shop did not supply this information | **UNCERTAIN** |
| `"not_applicable"` | The concept genuinely does not apply (a digital download has no return window) | A real, known answer — can legitimately FAIL a rule that demands otherwise |

The distinction between the middle row and the bottom row is worth internalising.
*"The shop didn't tell us whether you can return this"* is a reason to ask the
customer. *"This order genuinely cannot be returned, and you required
returnability"* is a real conflict with the policy, and declining is correct.

Early on, the engine treated `"unknown"` as an ordinary piece of text, which
meant a required `order_returnable = "true"` compared against `"unknown"` came
out as a definite mismatch and produced a **decline**. That was wrong: it punished
the customer for a shop's silence.

### 8.2 A check only speaks about what the policy asks

The `terms` check used to flag missing return terms on *every* purchase —
including grocery deliveries, under a policy that never mentioned returns. That
produced a `step_up` on ordinary shopping over a question nobody had asked.

The challenge brief is explicit that this counts as failure: *"blocking ordinary
shopping unnecessarily is also a failure."* A control layer that interrupts you
constantly gets switched off, and then it protects nobody.

So `terms` now stays quiet unless the mandate actually contains a rule about
return or cancellation terms.

### 8.3 Text from a shop is data, never instruction

Product descriptions, shop names, purchase descriptions — all of it is written by
whoever is trying to sell you something, and they may not be honest. The engine
may *compare* such text against known facts. It must never let it change a limit,
a rule, or a decision path.

The structural defence, as described in [section 4.3](#43-the-facts--what-an-ai-extracted-optional),
is that the component which reads shop text has no authority to grant anything.

### 8.4 The engine must not know which test it is taking

The practice data contains five named scenarios. It would be trivially easy — and
completely worthless — to write code that recognises "scenario 4" and produces
the answers someone expects there.

The challenge forbids it, and more importantly it would prove nothing. So the
`scenario_id` and the purchase's position in the sequence are **deliberately
discarded** when the event is parsed. They are not available to any check. This is
enforced by the shape of the data, not by everyone remembering to behave.

---

## 9. What is not finished

Right now, replaying all 45 practice purchases produces **6 declines and 39
step-ups, and zero approvals.**

That is not a bug, and it is worth understanding exactly why:

1. The two semantic checks always answer UNCERTAIN, because nothing produces
   `facts` yet.
2. Every practice scenario uses `uncertainty_policy: "ask"`.
3. So anything that is not outright declined becomes `step_up`.

The engine is behaving correctly given what it currently knows. But "correct" here
also means "not yet useful": a control layer that asks about *everything* is as
unhelpful as one that asks about nothing.

**Two pieces of work stand between here and a working demo:**

- **A policy compiler** — turning the customer's sentence (*"replace my worn
  road-running shoes in size 43…"*) into `hard_rules` plus a structured
  description of intent. Right now, rules are written by hand.
- **Fact extraction** — the AI step that reads product text and produces `facts`,
  so `item_match` and `purpose_fit` can actually answer.

Until both exist, the demo cannot show an ordinary purchase completing smoothly —
which is one of the three things the judges explicitly ask to see.

The thresholds in `session` (5 attempts, 3 attempts), `duplicate` (2 hours) and
`merchant` (82% name similarity) are also first guesses. The data pack contains no
answer key, so they were chosen for plausibility and are expected to be tuned once
the replay output can be judged properly.

---

## 10. Where the boundaries are

Things the engine deliberately does **not** do:

| Not the engine's job | Whose job it is |
|---|---|
| Calling the challenge API | `server/viseca/client.py` |
| Remembering decisions, budgets, history | `server/api/models.py` + `services.py` |
| Calling an AI model | The worker, before it calls `decide()` |
| The 8-second deadline and its fallback | `run_worker.py` |
| Showing the customer anything | The Expo app in `app/` |

If you find yourself wanting to add a database query or an HTTP call inside
`server/engine/`, that is the signal that the thing you are building belongs in
one of the rows above.

---

## 11. Seeing it for yourself

The fastest way to understand the engine is to watch it run. From `server/`:

```powershell
uv run python manage.py replay --scenario SCEN0001
```

This needs no API key and no internet — just `VISECA_DATA_DIR` pointing at your
clone of the challenge data pack. It prints one line per purchase: the decision,
the reason codes, the running approved total, and the evidence underneath.

To run the tests:

```powershell
uv run pytest tests/engine -v
```

These are pure and fast. If you change how a check thinks, this tells you within a
second whether you broke something else.

---

## 12. File map

```
server/engine/
├── decide.py        the entry point — start reading here
├── aggregate.py     turns many verdicts into one decision
├── types.py         every data shape, with the meaning documented per field
├── parsing.py       raw JSON → typed event (and where scenario_id is dropped)
├── reasons.py       every reason code, in one place
├── money.py         currency conversion and rounding
└── checks/
    ├── __init__.py       the two tiers, and why the order matters
    ├── amount.py         per-purchase hard rules
    ├── period.py         spending over a time window
    ├── merchant.py       familiarity, country, lookalike names
    ├── session.py        device, velocity, channel
    ├── duplicate.py      retries and accidental double orders
    ├── terms.py          return / cancellation requirements
    ├── item_match.py     STUB — needs AI facts
    └── purpose_fit.py    STUB — needs AI facts
```

Every module has a docstring at the top explaining its reasoning, including the
judgement calls made where the brief was ambiguous. Those docstrings are the
authoritative detail; this document is the map.

---

## Glossary

| Term | Meaning |
|---|---|
| **Mandate** | The customer's wallet policy as a stored record: their instruction, the machine-checkable rules, and what to do when unsure |
| **Hard rule** | One machine-checkable condition, e.g. *total ≤ CHF 120* |
| **Authorization** | One proposed purchase. The payments industry's word for "a request to spend" |
| **Check** | One small, focused test that returns PASS / FAIL / UNCERTAIN |
| **Verdict** | What a single check answered |
| **Decision** | What the whole engine answered: approve, decline, or step_up |
| **Evidence** | The specific facts a check used, kept so the decision can be explained afterwards |
| **Reason code** | A short, stable label such as `amount_limit_exceeded`, for machines and logs |
| **Step-up** | Pausing a purchase to ask the human |
| **Scenario** | One practice story from the data pack: a customer, a card, an instruction, and a series of purchases |
| **Replay** | Running a scenario's purchases through the engine offline, with no network |
| **Pure function** | A function whose answer depends only on what you pass in — no database, no clock, no network |
