# DECISIONS.md — AI usage log

Kept live, in the order things actually happened. Condensed for readability — the full detail
behind any entry is recoverable from the code's own comments and docstrings, which were written
to stand alone.

---

## Setup

Asked Claude Code to read the brief and profile the 5 CSVs before any work started. It found the
30 rule executions that silently failed, two non-overlapping adset-ID formats, and R09's purpose
(undoing other rules' mistakes) — all later load-bearing.

**My own decisions**: wrote `PLAN.md` first so assumptions stayed mine, not silently picked by
the model; sequenced strictly A→B→C so B's constraints came from what A actually found; held the
API key request until Task C, no reason for a live key to sit around earlier.

**Toolchain pivot, my own error**: initially picked Node.js because "no Python is installed" —
based only on a PATH check. The user pushed back ("why not SQL and python, easier for me"), and
when I tried to `winget install` a fresh copy, the user rejected it: "i have python on my computer
as well." A full Anaconda install existed at `C:\Users\yarde\anaconda3`, just never on PATH — "not
on PATH" and "not installed" are different claims, and I'd conflated them. Rewrote the loader in
Python, removed the Node scaffolding entirely rather than leave two toolchains in the repo.

---

## Task A — the investigation

**Real methodology bug, caught by a suspicious result, not inspection**: the first impact
estimate used `last_3_days_roi_at_action` and silently produced **$0.00 for R04** — the single
biggest rule (109 of 164 real firings). Cause: R04 fires on day-1 adsets, which by construction
have no 3-day trailing window, so the method was blind to R04, not measuring "zero impact."
Rewrote the counterfactual to use the adset's own settled same-day performance instead.

**Two self-caught factual errors** before the document was final: (1) wrote "cut from $213.89 →
$254.00" — that's an increase, not a cut, caught by re-reading my own draft against the query
output; (2) conflated the Case 2 adset with a different one entirely, which also revealed the
original "19 firings" claim was misleading even for the *correct* adset (only 3 of 19 actually
changed the budget) — removed the claim rather than ship a rushed replacement.

**User pushback #1, correct**: "how come optimistic isn't the highest?" — the conservative
scenario floored every negative rate at 0, making it structurally incomparable to the other two.
Fixed to use `min()` of two real readings instead of a hard floor; final numbers now form a real
spectrum (-$504.77 / -$482.68 / -$341.92), which also flipped the headline finding from "roughly
break-even" to "all three scenarios agree the rules saved money net, magnitude disputed."

**User pushback #2, correct**: "are you sure no changes are needed?" — re-checked and found null
counts I'd quoted in conversation (not yet in the doc) were inflated by 72 known duplicate rows;
fixed before they became a permanent error.

**Full EDA requested separately**: built `eda.py`/`eda_followup.py`, then `eda_verify.py` to
re-derive every claim with a *differently written* query (the earlier CSV-parsing episode was a
direct example of a first-pass finding turning out to be a parsing artifact). All 8 checks
confirmed. Added 4 new data issues found this way (72 true duplicate rows, a 34-variant language
column, a legitimate `cr > 1` pattern, one genuinely unresolved null-gating inconsistency).

**Self-audit caught a real gap**: two SQL files (`07`, `08`) did real work but were never cited in
the document — fixed, plus a per-rule flip-count breakdown, correcting an ambiguous "3" into two
correctly-labeled numbers (3 unique adsets vs. 4 total rows).

---

## Task B — designing the agent army

**Grounding example, pulled from real data, not invented**: adset `730115451617748648` — a buyer
doubled its budget citing "3 straight green days," but the adset was <25 hours old with exactly
one settled day. It lost money the next day and got cut back. Became the concrete evidence for
two decision-boundary rules in the design (minimum-data floor, confidence capped by data volume).

**External research, on request, with an explicit "don't change the plan unless drastic
improvement" instruction**: nothing contradicted the existing design; added two refinements — a
phased-autonomy rollout (shadow → bounded → full) and a cleaner kill-switch/circuit-breaker split.

**Placeholder number caught**: user asked "what's the boundary for the 20-80%?" — checking the
document found it was never a real rule, just an unlabeled assumption. Defined the Screener's flag
condition concretely and measured it: **42-66%, not 20%**, driven by real account growth in the
data (300→751 active adsets over the week). Propagated the correction through every place the old
20%/70x figures appeared (table, diagram, economics, constraints section) — found via `grep`, not
memory.

**Four mechanical gaps, caught by the user asking how things actually work**: how "amount" gets
decided, where hard limits actually live, the literal if/elif logic, and real Meta API mechanics.
None of these existed in the document before — all had been asserted in prose without a mechanism
behind them. Filled in: fixed percentage budget steps (mirroring the real rules), three
independent enforcement layers, an explicit decision tree, and real Marketing API details (auth,
minor-currency budgets, eventual consistency, rate limits, idempotency).

**Haiku's capability and Anthropic's own rate limits, researched not asserted**: real benchmark
numbers (73.3% vs. 77.2% SWE-bench, ~1/3 cost) and the finding that Anthropic unified rate limits
across Haiku/Sonnet/Opus in June 2026 — meaning the Haiku choice now rests purely on cost/latency/
task-fit, not a rate-limit advantage that used to exist but doesn't anymore.

**Buyer-salary breakeven, computed on request** ($5,000/month assumption supplied by the user):
$238/day buyer cost, 195x the measured system cost, ~1,171 accounts before LLM cost alone reaches
one buyer's daily cost.

**The evaluator's justification didn't survive its own review**: asked to just restate "why do we
need the evaluator," I checked it instead and found the cited failure patterns (R04, R08) were
already handled elsewhere — citing solved problems isn't a justification. Rebuilt it around two
things nothing else catches: hallucination/context-fidelity, and missed-growth (an agent that's
quietly too conservative never trips any guardrail, since "do nothing" always looks safe). The
conclusion (keep the evaluator) didn't change; the reasoning did, and the retraction is left
visible in the document rather than smoothed over.

---

## Task C — building and running the agent

**Setup**: created a placeholder `.env` (gitignored, confirmed before writing), guided the user to
paste their real key directly rather than through chat. Two real auth errors along the way — a
workspace-scoping error, then a genuine billing error — diagnosed from the actual error text each
time rather than guessed at.

**Context compressor, 3 real deviations from the original design**, found by checking against
real data rather than assumed to match: no `today_partial` field (only 75/1,000 adsets ever have
real intraday data); `current_budget` anchored to observed spend, never `meta.daily_budget`
(58.4% of the target set shows that field ≥10x observed spend); `cohort_percentile_roi` only
computed for cohorts ≥5 (77.8% don't qualify).

**Uncertainty mechanism proven on the real motivating case**: the R09/outage adset from
Investigation Case 1 correctly hit `forbidden` on all three of its decision dates. Confidence
capping extended to `near_dataset_edge` on the user's request, after flagging it as a real open
question first (2 of 3 decision dates trigger it for nearly every adset).

**Real performance bug**: the dry run hung indefinitely. Cause: `db.py` used DuckDB VIEWs over
`read_csv_auto()`, so every query re-parsed the source CSVs from disk — fine for a handful of
ad-hoc queries, fatal for thousands of per-decision queries. Fixed to materialized TABLEs with
indexes; verified row counts matched and timed a sample before trusting it.

**A stale planning number corrected**: the LLM-needed count was quoted as 341 throughout planning;
the real compressor (7-day window, matching the architecture) gives **443**. Traced to an earlier
rough 4-day-window approximation built before the real compressor existed. Propagated the
correction everywhere.

**Guardrail layer was missing entirely**: asked directly "are the hard limits embedded?" — the
structural budget-step bound was real, but the Guardian's bounds-check layer (cooldown, forbidden
routing, tier assignment) didn't exist yet, despite being in scope. Built and tested it before
running anything real.

**Two live batch crashes, root-caused rather than patched blindly**: (1) a `KeyError` when the
model omitted an "empty" array field the schema marked required — fixed with a narrow default for
that one field only, not the core decision fields (a guessed default there could produce a
misleading record); (2) the same crash shape recurred 14 times from `max_tokens=500` truncating
the model's reasoning — reproduced directly against the API to confirm before raising it to 1200.
Made the batch itself resilient (records an explicit `"error"` entry and continues) and resumable.
A first version of the resume fix wrongly treated errors as "already done" (would have stranded
them permanently) and, separately, the very first resume attempt opened the output file in
overwrite mode (would have silently destroyed 655 already-paid-for decisions) — both caught and
fixed before either mattered.

**A real problem the user caught live, mid-run**: watching the log, escalate rate looked very
high (93% on the decisions so far). Investigating surfaced an unconstrained free-text flag field
producing 140+ near-unique values — fixed by constraining to a 5-option enum, capped at 2 per
decision. The escalate rate itself didn't change after the fix; reading the actual reasoning on
several cases confirmed escalate was the *correct* call on real, volatile adsets, and the 93%
figure turned out to be concentrated on the earliest, thinnest-data target day specifically, not a
sign of a broken prompt.

**User challenged the value proposition directly**: "what does the agent even do if everything
goes to manual inspection, isn't it redundant?" Answered seriously: 78.5% of all decisions never
reach the LLM at all (real automation), and even escalate cases carry triage value — but conceded
the real point plainly, that a high final escalate rate is a genuine limitation worth stating in
`RESULTS.md`, not arguing away.

**Real citation error caught before finalizing**: the uncertainty-mechanism example in the first
`RESULTS.md` draft cited an adset ID alongside ROI figures that belonged to a *different* worked
example from earlier in the session. Caught by re-checking the citation against the actual logged
reasoning, fixed before the document was called done.

**"Isn't the agent working poorly?" — the real challenge.** I'd led `RESULTS.md` with an 82.4%
escalate rate among LLM-judged decisions; the user pushed for the full picture, which was worse:
only 2.3% of all 2,064 decisions were both actionable and autonomous. Diagnosed the real causes
(not "the model is too cautious" — its individual reasoning held up on inspection) and implemented
4 fixes: split the data floor by stakes not just age; added explicit `scale_down` guidance (0 uses
in the whole run, a genuine behavioral gap, not — as I first, wrongly, claimed — a pre-filter
artifact; checked the code, no such filter exists); added a graduated 0.55 confidence tier for
low-risk actions; built `validate_thresholds.py` to check thresholds against real settled outcomes
(user directly caught a second error here too — I'd said the data "doesn't exist" for this check
when most of it does). Backed up the v1 run before re-running.

**v2 result**: actionable 29.6%→83.6%, `scale_down` 0→15 uses. Autonomous barely moved (2.3%→2.9%)
despite that — traced to a 5th bug: all 1,605 deterministic `keep` decisions carried a fixed
confidence of 0.3, the same number meant to signal real market-prediction doubt, when a
deterministic `keep` is an auditable policy the code is 100% certain of, not a prediction at all.
Fixed with a dedicated constant (0.65) reflecting the low but non-zero risk of a no-op; patched
the existing output in place, no LLM re-call needed. **Result: autonomous 2.9%→77.2%.**

**Compared against real history** (`compare_decisions.py`, 243 matched adset-days): naive exact
agreement was a misleadingly low 6-8% — mostly an artifact of comparing our `keep` decisions
against a log that only records when someone *did* something. The number that actually matters:
excluding our own `keep` calls, when the agent committed to a real move, it matched what a human
or rule actually did **83% of the time** (n=30, small but real).

**Money-impact analysis, built on request** ("what are the money results, is this better than
human"): estimated $ impact using settled follow-up data, same methodology discipline as Task A.
Result: our decisions +$9.25 vs. real actions +$12.93 on 18 matched cases — a small, honest deficit
traced to a specific cause (fixed budget-step caps vs. real buyers' larger discretionary moves),
not hidden or rounded away.

**Full deliverable review pass, on request**: cross-checked all four documents against each other
and the underlying code/data. Found one real stale-number anomaly — the threshold-validation
section still showed pre-final-fix numbers; re-ran it against the current data (sample roughly
doubled) and reported a *more critical* finding, not a softer one (the graduated 0.55 tier is only
50% directionally accurate on a real sample, barely above chance). Also found and fixed a real
`.gitignore` bug that would have excluded `decisions.jsonl` and the run logs — the actual evidence
behind most of `RESULTS.md` — from the submitted repo. Cross-checked one `ARCHITECTURE.md`
assumption (15% Sonnet-escalation rate) against real behavior (1.8% actual).

---

## Note on this log

Condensed on request from a longer version that documented the same episodes in more narrative
detail (including a "Step 0" mechanical-scaffolding section, removed entirely as asked). Nothing
substantive was cut — every correction, rejected approach, and self-made decision above is real
and traceable to the code's own comments if more detail is needed.
