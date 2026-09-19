# Setting up the local model

How to get fact extraction running on a local model, so product text never
leaves the machine.

> **Not verified on a Mac.** This was written on a Windows machine with no
> Ollama installed, from the Ollama documentation and the code in
> `server/facts/local.py`. The commands are straightforward but treat the
> troubleshooting section as the important part — especially
> [thinking mode](#61-everything-is-far-too-slow), which is the most likely
> thing to go wrong.

**Target machine:** MacBook Pro, Apple Silicon (M5), 16 GB unified memory.
Windows equivalents are in [§8](#8-windows), along with when not to bother.

---

## 1. What this is for

The decision engine needs structured facts about each cart line — is this a
sporting-goods item, what size is it, how long is the return window. That
information only exists as free text the merchant wrote, so something has to
read it.

`server/facts/` has three interchangeable backends:

| Backend | Reads text? | Needs |
|---|---|---|
| `stand-in` | No | Nothing |
| `local` | Yes | Ollama running here ← **this guide** |
| `hosted` | Yes | An Anthropic API key |

Which one runs is an environment variable. Nothing else in the system changes.

**Why bother with local:** product text never leaves the machine, and the
workload suits it — across the whole challenge data pack, `item_details`
averages 56 characters and never exceeds 276. Pulling a size out of one
sentence is extraction, not reasoning.

**Note on the stand-in:** it cannot verify anything, so with `stand-in` the
system approves nothing and asks about everything. That is correct behaviour,
not a bug — but it means the offline replay only becomes informative once a
real backend is running. Getting this working is on the critical path.

---

## 2. Install Ollama

Either works:

```bash
brew install ollama
```

or download the app from <https://ollama.com/download> and open it.

**Check whether it is already running before starting anything:**

```bash
curl http://127.0.0.1:11434/api/tags
```

A JSON response — even an empty model list — means the server is up and you can
go straight to the next section.

The macOS app starts the server itself in the background, so in most cases it
already is. Only run `ollama serve` if the command above fails to connect.

> **`listen tcp 127.0.0.1:11434: bind: address already in use`** is not a
> problem: it means a server is already listening, which is what you want. Use
> the `curl` above to confirm, then carry on. `lsof -i :11434` shows what holds
> the port. To genuinely restart: quit the Ollama app, or
> `brew services stop ollama`, then `ollama serve`.

---

## 3. Pull a model

Start small, and **pick a model with no reasoning mode**.

```bash
ollama pull qwen2.5:3b
```

This is extraction, not thinking: pulling "size 43" out of one sentence needs
reading, not deliberation. A reasoning model will generate a thinking trace
before every answer, which is pure latency against an 8-second deadline — and
switching that off depends on your Ollama version honouring `think=false`, which
is one more thing to go wrong under demo pressure. A model that cannot think has
nothing to disable.

**Check the tag exists first** — the registry changes, and this document may be
older than what is published:

```bash
ollama list                                  # what you already have
# or browse https://ollama.com/library/qwen3
```

### Which size for 16 GB

macOS, Postgres, Django and the Expo dev server share that memory with the
model. Realistically you have 6–8 GB for the model.

| Model | ~4-bit size | Verdict |
|---|---|---|
| **Qwen2.5 3B** | ~2 GB | **Start here.** No reasoning mode, fast, enough for this |
| Qwen2.5 7B | ~4.5 GB | Step up only if 3B measures too weak |
| Qwen3 (any size) | — | Only if you have verified `think=false` works on your version |
| 14B and larger | ~9 GB+ | Don't. Too little room for everything else |

Bigger is not obviously better here. The input is one sentence and the output is
schema-constrained, so a larger model mostly buys latency.

Quick sanity check that the model answers at all:

```bash
ollama run qwen2.5:3b --verbose "Reply with the single word: ok"
```

`--verbose` prints timings — tokens per second and total duration. That is the
number to watch when tuning.

> **If you use a reasoning model anyway** (Qwen3, DeepSeek-R1, …), the CLI
> enables thinking by default, so it will deliberate at length over even a
> one-word prompt. `--think=false` disables it where the version supports it,
> `/no_think` in the prompt is Qwen3's own switch, and `facts/local.py` sends
> `think=False` on every API request. If any of those fails to take effect,
> that is the argument for a non-reasoning model, not for fighting the switch.

---

## 4. Point the project at it

In `server/.env`:

```
FACTS_BACKEND=local
OLLAMA_HOST=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3:4b
FACTS_TIMEOUT_SECONDS=4
```

`FACTS_TIMEOUT_SECONDS` must leave the worker's watchdog room to act — it
submits a deterministic-only decision when two seconds remain before the
deadline. Four seconds for extraction fits inside the eight-second budget with
room for the rest of the round trip.

The Python client is already a dependency (`uv sync` covers it).

---

## 5. Run it

```bash
cd server
uv run python manage.py replay --scenario SCEN0002 --facts local
```

`SCEN0002` is the right test: the customer wants shoes in **size 43**, and that
size only exists in free text. The stand-in cannot read it, so a working local
model is immediately visible in the output.

### What good looks like

Every run ends with a coverage line:

```
Facts from ollama:qwen3:4b: 12/13 lines got a category, 11/13 got attributes.
```

| What you see | What it means |
|---|---|
| Category and attribute counts close to the line count | Working |
| `0/13 ... 0/13` plus a `WARNING` | Nothing was read — see §6 |
| Categories but no attributes | The model classifies but is not reading detail text |

Individual purchases should move off `STEP_UP` — some to `APPROVE` (the shoe is
size 43), some to `DECLINE` (it is size 42, or the basket has an add-on).

**The coverage line exists precisely so a dead backend cannot be mistaken for a
measured one.** If it reads zero, you measured nothing — do not record a result.

---

## 6. Troubleshooting

### 6.1 Everything is far too slow

**Thinking mode is already off.** Qwen3 models can generate reasoning before
answering; for a one-sentence extraction that is pure latency and would blow the
deadline. `local.py` sends `think=False` on every request, controlled by
`OLLAMA_THINK` in `.env` (default `false` — leave it).

If a log line says your installed client has no `think` parameter, it is too old
to send it. Either upgrade (`uv add ollama` pulls the current release) or disable
reasoning at the model level.

Note that the **CLI defaults the other way**: `ollama run` enables thinking for
capable models, so a slow or silent `ollama run` says nothing about how the
extractor behaves. Use `--think=false` when testing by hand, and trust the
replay over the CLI.

Remaining suspects, in order:

1. **A cold model** — see §6.2.
2. **`num_ctx` too large.** `local.py` pins it to 2048 because our prompt is a
   few hundred tokens; a larger window costs KV-cache memory for nothing.
3. **Too little memory.** Check with `ollama ps` and see §6.5.

### 6.2 The first request after a pause is slow, then it is fine

Ollama unloads an idle model after a few minutes. The next request pays the
reload — which against an 8-second deadline is a missed deadline.

`local.py` already sends `keep_alive=-1` (stay resident) and exposes
`warm_up()`. Confirm the model is actually held:

```bash
ollama ps
```

The listed model should show no near expiry. Call `warm_up()` when the worker
starts, and if you are about to demo, run one throwaway extraction first.

### 6.3 `0/13 lines got a category` and a warning

The backend was unreachable or failed. In order:

```bash
curl http://127.0.0.1:11434/api/tags     # is the server up?
ollama list                              # is OLLAMA_MODEL actually pulled?
```

Check `OLLAMA_MODEL` in `.env` matches a tag exactly — `qwen3:4b` and `qwen3`
are different tags.

To see the actual error rather than the summary, raise Django's log level or
run the extractor directly:

```bash
uv run python manage.py shell
```
```python
from facts import build_extractor
from facts.base import ExtractionItem
e = build_extractor("local")
print(e.extract([ExtractionItem(1, "Road-running shoes", "size 43; returns 30 days")]))
```

Failures are logged as warnings by design — no backend may raise into the
decision path — so the direct call is the quickest way to see what went wrong.

### 6.4 Categories come back but attributes do not

The model is classifying but not reading detail text. Try, in order: a larger
model (`qwen3:8b`), then the prompt in `facts/base.py`. Note that
`SYSTEM_PROMPT` deliberately tells the model to **omit rather than infer** — a
missing attribute becomes a question to the customer, while an invented one
could wrongly decline a purchase. Keep that instruction when you edit.

### 6.5 The machine runs out of memory

Close the Expo dev server, or drop to a smaller model. `ollama ps` shows what
is resident; `ollama stop <model>` unloads it.

---

## 7. Comparing local against hosted

The point of the swappable backend is that this is measurable rather than
arguable. Same inputs, same replay, one variable changed:

```bash
uv run python manage.py replay --scenario SCEN0002 --facts stand-in > /tmp/standin.txt
uv run python manage.py replay --scenario SCEN0002 --facts local    > /tmp/local.txt
uv run python manage.py replay --scenario SCEN0002 --facts hosted   > /tmp/hosted.txt
diff /tmp/local.txt /tmp/hosted.txt
```

`hosted` needs `ANTHROPIC_API_KEY` in `server/.env` — a **different** key from
`VISECA_API_KEY`.

Record, for each backend: extraction coverage, the decision mix, and wall-clock
time. Those three numbers turn §3.6 of `docs/PITCH.md` from a claim into a
measurement. Until you have them, do not quote numbers in the pitch.

---

## 8. Windows

The project's own commands are unchanged — `uv run python manage.py replay ...`
works the same. Only the Ollama side differs.

### Is this machine worth it?

Check before installing anything:

```powershell
Get-CimInstance Win32_VideoController | Select-Object Name
(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB
```

**A discrete GPU with 6 GB+ of VRAM:** fine, proceed.

**Integrated graphics only (Intel UHD / Iris), or under 16 GB RAM:** inference
falls back to the CPU. For a 4B model that is tens of seconds per extraction
against an **8-second decision deadline** — the watchdog will fire every time.
Do not use this machine for the local backend. Options, best first:

1. **Run Ollama on the Mac and point this machine at it.** Set
   `OLLAMA_HOST=http://<mac-lan-ip>:11434` in `server/.env` here, and on the Mac
   bind it externally with `launchctl setenv OLLAMA_HOST 0.0.0.0:11434`
   (restart Ollama afterwards). The text still never leaves your network.
2. **Develop against `hosted`** here and measure `local` on the Mac.
3. **A very small model** (`qwen3:0.6b`, ~400 MB) purely to prove the wiring.
   Expect poor extraction quality; do not measure anything with it.

### Commands

```powershell
winget install Ollama.Ollama

# Already running? (the installer starts it and adds a tray icon)
Invoke-RestMethod http://127.0.0.1:11434/api/tags

# What holds port 11434
Get-Process -Id (Get-NetTCPConnection -LocalPort 11434).OwningProcess

ollama pull qwen3:4b
ollama run qwen3:4b --think=false "Reply with the single word: ok"

ollama ps                 # what is resident
ollama stop qwen3:4b      # unload it

# Optional limits on a memory-constrained machine.
# Restart Ollama from the tray icon afterwards.
[Environment]::SetEnvironmentVariable("OLLAMA_MAX_LOADED_MODELS","1","User")
[Environment]::SetEnvironmentVariable("OLLAMA_NUM_PARALLEL","1","User")
```

`server/.env` is identical to §4.

---

## 9. Security properties worth knowing

Set out in full in `server/facts/base.py`. Three rules hold for every backend,
local included:

1. **No backend ever sees the customer's policy** — not the limits, not the
   mandate, not even which attributes a rule cares about. Merchant text saying
   *"ignore the spending limit"* reaches a component that holds no limits and
   can grant nothing.
2. **Only structured values come back** — a category from a fixed vocabulary of
   seven, plus five attribute strings. No free text, no judgements.
3. **Failure is silence, not a guess** — timeout, crash, unparseable response,
   or a value outside the schema all become *absent* facts, which the engine
   reads as uncertainty and turns into a question for the customer.

Rule 3 is why a local model is safe to experiment with: the worst it can do is
make the system ask more often.
