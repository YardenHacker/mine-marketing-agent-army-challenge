# PLAN.md — Mine Marketing: "The Agent Army Challenge"

> **Working document.** Editable at any point. Check boxes as steps complete.
> **Status:** Tasks A, B, and C complete. `INVESTIGATION.md`, `ARCHITECTURE.md`, `RESULTS.md`
> all written, each corrected through real review rounds — see `DECISIONS.md` for the full
> history, including two bugs caught live during the actual batch run and two direct user
> challenges that changed the design. The 2,064-decision batch ran clean (0 errors, $2.04 total
> spend). Task D (`DECISIONS.md`) has been live and continuous since Step 0. Remaining:
> `README.md` and the git repo/commit.
> **Executor note:** this file is self-contained. Read it top to bottom before acting.
> Do not re-derive the findings in §2 — they were verified against the data already, and were
> extended further during Task A/B work — see `INVESTIGATION.md` and `ARCHITECTURE.md` directly
> for anything not captured here.

---

## 0. Locked decisions

| Decision | Choice | Rationale |
|---|---|---|
| Stack | **Python 3.13 (Anaconda, already on this machine) + DuckDB**, `anthropic` Python SDK for Task C | **Superseded from the original Node.js+DuckDB plan.** The user asked for SQL+Python mid-Task-A; the original "no Python on this machine" finding was wrong — an existing Anaconda install just wasn't on PATH. Rebuilt `src/db.js`→`src/db.py`; full story in `DECISIONS.md`. |
| API key | **Now being set up — Task C reached.** Read from `ANTHROPIC_API_KEY` via a `.env` file (already created, already gitignored); never pasted in chat, never hardcoded, never committed. | Keeps the key out of the transcript and the repo. |
| Sequence | **A → B → C, strictly.** (followed) | B's constraints and C's guardrails were derived from real Task A findings, not assumed — confirmed this held in practice (the revenue-delay number, the R09 case, the R02 cooldown finding all became concrete Task B design decisions). |
| Task D | Written **continuously**, not reconstructed at the end. (followed) | `DECISIONS.md` has a live entry for every stage, correction, and user pushback so far — including several real self-caught errors, not just a clean narrative. |
| Repo | `git init` in this folder early; commit per task. | Submission requires a git repo. **Not yet committed to git** — no commits made this session; do not commit without being asked. |
| Task C scope | **One agent only — the Analyst (Adset Decision Agent).** No live Executor (nothing to write to — this runs against the snapshot, not a real account); Guardian logic implemented as output validation only, not a standing service. | Confirmed explicitly with the user when starting Task C — the brief says "implement one agent," singular. |
| Task C context object | **Built from `ARCHITECTURE.md` §5's design, with three real, checked deviations** (`src/context_compressor.py`): no `today_partial` field (only 75/1,000 adsets in the whole dataset ever have real intraday data — fabricating it for the rest would be worse than omitting it); `current_budget` anchored to observed trailing spend, never `meta.daily_budget` directly (58.4% of the target set shows that field ≥10× observed spend); `cohort_percentile_roi` only computed for cohorts ≥5 members (77.8% of the target set doesn't have one — `null` + flagged, not fabricated). Fields: adset_id, decision_date, account, vertical, age_days, trailing_daily (≤7 days), current_budget, declared_budget_meta, recent_actions, cohort_size, cohort_percentile_roi, data_quality_flags, mandate_reminder. | Task B designed the shape; Task C's job was to build it and found real places the live design didn't match this snapshot's actual data — all three deviations are measured, not guessed, and logged in `DECISIONS.md`. |
| Task C model choice | **Haiku 4.5 default, Sonnet 5 on escalation** — same split as `ARCHITECTURE.md` §3, grounded in real benchmarks (73.3% vs 77.2% SWE-bench, ~1/3 the cost) and the June 2026 finding that Anthropic rate limits no longer differ by model. | Consistency between the designed architecture and the built slice; no new justification needed, it's already in `ARCHITECTURE.md`. |
| Task C pre-filter | **Measured against the real, final compressor code** (`context_compressor.py`, 7-day trailing window, matching `ARCHITECTURE.md`'s design): of the 2,064 required adset-day decisions, **1,621 (78.5%) fall below the minimum-data floor** (<2 settled days or <$5 trailing spend over the full available window) and get a deterministic, code-authored `keep`/`escalate` — no LLM call. **443** genuinely need real judgment. (Earlier in this session a rough pre-implementation estimate said 1,723/341 — that used a narrower 4-day trailing-spend window as a planning-stage approximation, before the compressor existed; the 1,621/443 figures here are the accurate ones, from the actual code.) | **Not primarily cost control** — the worst-case ceiling (all 2,064 on Haiku) is still comfortably under the $10 cap, so cost was never actually at risk either way. The real reason: this is the concrete, code-enforced implementation of Task C's most-valued requirement ("recognize when it doesn't know, not guess confidently") — an adset with <2 settled days doesn't have enough information for *any* reasoner, human or AI, to produce a trustworthy judgment, so deciding it in code removes the risk of an LLM being confidently wrong on thin data the way the real buyer was (`730115451617748648`, "3 straight green days" on a 1-day-old adset). Cost savings is a real but secondary side-benefit. |
| Task C cost estimate | **~$1.80 recommended** (443 real calls, no escalation) — **~$3.46** with ~15% escalating to Sonnet — hard ceiling enforced in code at **$6.00**. All comfortably under the $10 cap. | Computed from real observed per-call cost (the two test decisions in `llm_decision.py`), not guessed — see `DECISIONS.md`. Print the real estimate again immediately before the full run and get explicit go-ahead, per the standing rule below. |

**Working dir:** `C:\Users\yarde\Documents\Apps\Mine Marketing Assingnment`
**Data:** `./dataset/` (already unzipped — 5 CSVs + `README_DATA.md`)

---

## 1. The brief in one paragraph

A performance marketing company runs Meta campaigns across six ad accounts. Expensive human
media buyers make dozens of daily decisions; 12 threshold-based auto-rules also run. Design and
prove out an AI agent system that replaces most of the buyers' decision-making — profitably,
safely, cost-effectively.

**The mandate that governs every answer:** *maintain or grow total spend AND absolute profit
while improving efficiency.* The brief warns: "An agent that pauses everything would score a
great ROI and destroy the business." Every metric, guardrail and eval must be robust to that
failure mode. If a proposed metric can be gamed by shrinking, it is the wrong metric.

---

## 2. Verified data findings (do not re-derive)

Window: **2026-06-06 → 2026-06-12** (7 days), accounts ACC-01…ACC-06.

| File | Rows | Notes |
|---|---|---|
| `daily_adset_performance.csv` | 4,947 | 1,000 unique adsets |
| `campaign_adset_metadata.csv` | 7,129 | 4,023 ACTIVE / 3,014 PAUSED / 92 DELETED; only **305** have `delivery_status=ACTIVE` |
| `auto_rules.csv` | 12 | rule logic encoded in the rule *name* string |
| `rule_executions.csv` | 214 | equals the sum of `firings` in `auto_rules.csv` exactly |
| `buyer_actions.csv` | 1,001 | only 24 rows have a free-text `note` |

### 2.1 Confirmed data issues (Task A deliverable #3 — all already verified)

1. **~23% of rule executions never took effect.** `response` = 164 `SUCCESS`, 20
   `"No budget to change"`, **30 `{"status":"error","code":190,"message":"access token invalidated"}`**.
   The rule engine logged actions it never actually performed. Any attribution treating the log
   as ground truth is wrong. → *Impact math must filter to `SUCCESS`, and the failures are
   themselves a finding: silent automation failure with no alerting.*
2. **Two distinct adset-ID namespaces.** IDs are 14-digit or 18-digit and are **genuinely
   different adsets, not truncations** (verified by suffix matching — no overlap).
   - `rule_executions`: 100% 14-digit (75 unique adsets, all of which join cleanly to both
     `perf` and `metadata`)
   - `perf`: 117 fourteen-digit + 883 eighteen-digit unique
   - `buyer_actions`: mixes both, **plus 286 rows with an empty `adset_id`** (campaign-level actions)
   - `metadata`: 2 rows with 6-character IDs (malformed)
3. **CSV parsing trap.** The 30 error `response` values contain JSON with embedded commas.
   Naive comma-splitting shifts columns and silently corrupts those rows. **Use a real CSV parser
   / DuckDB `read_csv_auto`.** Verify parsed `rule_id` values are only R01–R12.
4. **`old_budget` ≠ `current_budget_from_fb`** on many rows — the reporting system and Meta
   disagree about the live budget. The rules acted on the stale reporting value. Quantify this.
5. **Metadata covers 7,129 adsets but only 1,000 ever spent** in the window. Joining naively
   inflates denominators.

### 2.2 Confirmed rule-behaviour findings (Task A deliverables #1 and #2)

| Rule | Fires | Why it matters |
|---|---|---|
| **R04** `Turn Off - OWN RSOC / Total Days = 1 / budget > 35% / ROI < -50%` | **109 (51% of all firings)** | Judges **day-1** adsets on **partial-day** ROI while revenue is still arriving. Prime "killed a winner" candidate. |
| **R09** `Turn On / Automation Mistake - Today / OWN RSOC` | 8 | **The system has a rule whose job is to undo the other rules.** This is the thesis of Task A handed over on a plate. Every R09 firing is a self-admitted rule error — trace each one back to the rule that caused it. |
| **R02** `Budget Decrease / -30 < ROI <= -10` (−20%, min 9) | 23 | One adset (`31626016833981`) hit it **19 times**. Rules run every 30 min with **no cooldown** → compounding −20% cuts. The R01 sample also shows the *same* adset firing twice within 30 min, `SUCCESS` both times. |
| R03 / R11 | 36 / 2 | `positive_days = 0` — near-duplicate rules with overlapping conditions (`total_days > 2` vs `> 3`). Check for double-firing. |
| R01 / R08 | 4 / 15 | Pure age-based kills (`Total Days >= 5`, `= 4`) — **no performance condition at all**. |
| R05, R06, R07, R10, R12 | 7, 1, 1, 2, 6 | Low-volume; check for dead or misconfigured rules. |

### 2.3 Aggregate shape (context, not conclusions)

Rows/day climb 357 → 999 while daily spend **falls** 1,216 → 843 and daily ROI oscillates
(0.257, 0.039, 0.056, 0.083, 0.027, 0.182, 0.062). Part is new adsets entering; part is likely
the **revenue-arrival delay** the brief tells you to characterize. **Do not assume — measure it
in A1.5 below.**

---

## 3. Execution plan

### Step 0 — Repo scaffolding
- [x] `git init`; add `.gitignore` (`node_modules/`, `.env`, `*.duckdb`, scratch outputs)
- [x] `npm init -y`; install `duckdb` (or `@duckdb/node-api`) and `@anthropic-ai/sdk`
- [x] Create `DECISIONS.md` **now** and start logging from this step onward
- [x] Layout:
  ```
  /dataset            given CSVs, committed
  /sql                Task A queries
  /src                loaders, agent, context builder
  /out                generated results (decisions.jsonl, comparison tables)
  INVESTIGATION.md ARCHITECTURE.md RESULTS.md DECISIONS.md README.md PLAN.md
  ```
- [x] `src/db.js` — one loader that registers all 5 CSVs as DuckDB views with **explicit column
      types** and normalised `adset_id` as TEXT (never let it become a float or bigint)

---

### Step A — Investigate before you automate → `INVESTIGATION.md`

**A1. Reconstruct what the rules did**
- [x] A1.1 Parse the 12 rule names into structured conditions (table: rule_id, trigger metric,
      operator, threshold, action, magnitude, floor). Note explicitly that thresholds inside rule
      names are **percentages** (`ROI <= -50` means ratio `-0.50`) per `README_DATA.md`.
- [x] A1.2 Join `rule_executions` → `perf` → `metadata` on normalised adset_id. Report join
      coverage (expected: 75/75 unique adsets match).
- [x] A1.3 Split executions into **effective** (`SUCCESS`, n=164) vs **no-op** (n=20) vs
      **failed** (n=30). All impact math uses effective only; the other 50 become a data-issue
      finding and a Task B failure mode.
- [x] A1.4 Per rule: firings, unique adsets touched, spend/revenue/profit of affected adsets
      before vs after the action.
- [x] **A1.5 Characterize the revenue delay.** *Required for Task B's hard constraint.* Compare,
      for the same adset-day, `today_roi_at_action` / `spend_at_action` recorded at execution
      time against the final `roi` / `spend` in `daily_adset_performance`. Quantify: how much
      does same-day ROI understate final ROI, and how does the gap shrink by hour of day?
      **This number is the most load-bearing fact in the whole submission** — it justifies Task A's
      "killed winners" claim, Task B's cycle design, and Task C's uncertainty mechanism.
- [x] A1.6 Same for budget drift: distribution of `old_budget` − `current_budget_from_fb`.

**A2. Quantify money saved/burned — state assumptions explicitly**
- [x] Build a **counterfactual**. There is no single correct method; the brief says so. Recommended:
  - For a **pause**: estimate what the adset would have earned over the remainder of the day and
    following days, using its own trailing performance and matched-cohort recovery rates
    (adsets with similar day-N ROI that were *not* paused — the R09 reactivations give a natural
    control group).
  - For a **budget cut**: forgone profit = budget delta × realised profit-per-dollar of that adset
    in the following window, floored at zero when the adset's true ROI was negative.
  - Report **three scenarios** (conservative / central / optimistic) rather than one fake-precise
    number, and show the sensitivity.
- [x] Attribute per rule: saved $X, burned $Y, net $Z. Rank the 12 rules.
- [x] Collect every assumption in a numbered block. Reviewers grade the methodology, not the number.

**A3. Two+ concrete cases a competent human would not have made**
- [x] Case 1 — strongest candidate: an **R09 reactivation**. Trace it back: which rule killed it,
      what that rule saw, what was actually true. The system admitting its own error.
- [x] Case 2 — strongest candidate: the **R02 19× compounding cut** on `31626016833981`, or an
      **R04 day-1 kill** where revenue arrived after the pause and the adset was in fact profitable.
- [x] For each: what the rule *saw* vs what was *true*, and what it was **missing** (delayed
      revenue, no trend, no cohort context, no cooldown, stale budget) or **misreading**.
- [x] Also look for a "let a loser run" case — leadership's suspicion is bidirectional, and the
      age-only rules (R01/R08) plus the low-firing rules are where to look.

**A4. Data issues** — write up §2.1 with how each was handled and how it was checked.

**Deliverable check:** `INVESTIGATION.md` + every query in `/sql` (or `/src`), runnable.

---

### Step B — Design the agent army → `ARCHITECTURE.md` (no code)

Must answer all five, at minimum:

- [x] **B1. Agent topology.** One or many. If many: roles, and *why this split*. For each agent
      state precisely **what it sees** and **what it can do**. Suggested spine (adapt to findings):
      a deterministic **Screener** (SQL, no LLM), an **Adset Decision Agent** (LLM judgment — the
      one built in Task C), an **Executor** (code, no LLM, applies changes and verifies them
      against Meta), an **Auditor** (reconciles intent vs actual — directly motivated by the 30
      silent failures), and a **Portfolio agent** enforcing the account-level spend/profit mandate
      so no local decision starves the portfolio.
- [x] **B2. Decision boundaries.** Three buckets — autonomous / needs human approval / forbidden —
      with **concrete numbers**: max % budget change per action, max absolute $ change, max actions
      per adset per day, **cooldown between actions on the same adset** (straight from the R02 19×
      finding), max daily exposure per agent, minimum spend/conversion volume before any decision
      is permitted at all.
- [x] **B3. Economics.** Show the math: decisions/day × tokens/decision × price/token, per model.
      Use current Anthropic pricing (verify it, don't recall it). Answer: at what account scale
      does this beat a media buyer's salary? Where a **cheap** model, where an **expensive** one,
      and — explicitly asked — where **no model at all** (plain code/SQL). Must fit **$30/day
      across six accounts**. Note ~2,064 active adset-days over 3 days as the real workload scale.
- [x] **B4. Failure modes.** Top 5 ways this loses money or breaks + a guardrail each. Include
      **kill-switch design**: who or what trips it, its scope, how state is restored, how it fails
      safe. Ground at least two in Task A evidence (silent API failure; compounding no-cooldown actions).
- [x] **B5. Data flow.** What is pulled **every cycle** vs **cached** vs **queried on demand**;
      how raw tables become decision-ready context; how `buyer_actions.csv` history factors in
      **and the risks of relying on it** (only 24/1,001 rows carry notes; 286 rows have no
      adset_id; buyer intent is largely unrecorded — imitating them encodes their mistakes).
- [x] **B6. Diagram** — at least one. Mermaid preferred.

**Hard constraints to honour and reference explicitly:** $30/day LLM budget; delayed revenue
(use the measured number from A1.5); Meta API rate limits (can't poll everything every minute).

---

### Step C — Build one working slice → code + `RESULTS.md`

**Scope confirmed with the user: one agent only — the Analyst (Adset Decision Agent).** No live
Executor (nothing real to write to); Guardian logic is applied as output validation, not stood up
as a running service. Run for each active adset on **2026-06-10, 2026-06-11, 2026-06-12**
(607 / 706 / 751 active adsets = **2,064 required decisions**).

**Context object: already designed, not to be redesigned.** Use the exact JSON shape from
`ARCHITECTURE.md` §5 ("Analyst receives...") — see §0 above for the field list. Reusing this
directly is the point: Task B designed it, Task C proves it works.

**Pre-filter: measured against the real, final compressor code, not a pre-implementation
estimate.** Of the 2,064 required decisions, **1,621 (78.5%) fall below the minimum-data floor**
(`spend_day_no < 2` OR `< $5` total spend over the full 7-day trailing window) — these get a
deterministic, code-authored `keep`/`escalate` with a template reasoning string, **no LLM call**.
**443** clear the floor and get a real model call. (A rough pre-implementation estimate earlier
in this session said 1,723/341, using a narrower 4-day window before the compressor existed —
443 is the accurate figure, measured against the actual code.) This *is* C1's "no model at all
where a model isn't needed" requirement, grounded in a real count.

**Model choice: Haiku 4.5 default, Sonnet 5 on escalation** — same split as `ARCHITECTURE.md` §3
(low confidence or genuine ambiguity triggers escalation), same benchmark justification already
established there. Don't re-litigate this in Task C — implement what's already decided.

Output schema (minimum — extend it and justify each addition in `RESULTS.md`):
```json
{
  "adset_id": "...",
  "decision_date": "...",
  "action": "scale_up | scale_down | pause | keep | escalate",
  "amount": null,
  "confidence": 0.0,
  "reasoning": "...",
  "data_quality_flags": ["..."]
}
```
Recommended additions (justify in RESULTS.md): `expected_profit_impact`, `evidence` (the exact
compressed facts used), `assumptions`, `counterfactual_if_wrong`, `cooldown_until`,
`requires_human_approval`, `model_used`, `input_tokens` / `output_tokens` / `cost_usd`,
`llm_called: bool` (explicit — did this decision come from the model or the deterministic floor).

- [ ] **C0. Environment setup.** `.env` file created (gitignored, placeholder only — see
      `DECISIONS.md`). User provides the real key via Anthropic Console → API Keys, sets a
      Console-side spend limit as a second safety net. Install the `anthropic` Python SDK. One
      tiny smoke-test call (~$0.001) to confirm connectivity **before** any real spend.
- [x] **C1. Real LLM call for the judgment layer.** Cost estimate, computed from real observed
      per-call cost, not guessed: **~$1.80 recommended** (443 real calls, no escalation) —
      **~$3.46** with ~15% escalating to Sonnet — hard ceiling enforced in code at **$6.00**,
      all comfortably under $10.
      - **Print the real cost estimate again immediately before the full run and get explicit
        user go-ahead** — not just the estimate given during planning.
      - A **hard spend ceiling in code** that aborts the run if actual spend exceeds the ceiling
        — implemented and checked before every LLM call, not just at the end.
      - **Ran on a small sample first** (the 2 worked examples from the compressor demo, ~$0.008
        total) — verified output quality/format, caught and fixed a real confidence-cap reporting
        bug from reading the actual output — *then* the full run.
      - **Also caught and fixed a real performance bug** while building the full-batch runner:
        `db.py` registered the CSVs as DuckDB VIEWs, which re-parse the source CSV from disk on
        every query — fine for Task A/B's handful of ad hoc queries, but fatal for a batch run
        issuing thousands of queries. A dry run hung indefinitely with zero output; fixed by
        materializing as TABLEs with indexes (see `DECISIONS.md`), confirmed via a 50-row timing
        test (47ms/context) before re-running the full 2,064-row estimate.
- [x] **C2. No raw tables to the model.** Implement the context compressor producing the exact
      object from `ARCHITECTURE.md` §5. Document real measured token counts per decision (not
      just the architecture's estimate) and show a real worked example in `RESULTS.md`.
- [x] **C3. The uncertainty question — *they say this is what they care about most.***
      Implement the layered mechanism already designed in `ARCHITECTURE.md` §2's decision logic:
      - **Deterministic pre-flight gates** (the minimum-data floor above, the revenue-delay
        window from A1.5, `old_budget` ≠ `current_budget_from_fb`, unreconciled failed rule
        executions, conflicting recent human vs. rule action) force `escalate`/`keep` before the
        model runs, or cap the confidence of what it returns.
      - **Confidence must be earned, not asserted** — cap it against the evidence actually
        present; reject high confidence on thin data, per the Guardian's rule in `ARCHITECTURE.md`.
      - Make `escalate` a **first-class, rewarded** outcome, and prove it fires on a real case
        from the data (there should be several, given 1,621 of 2,064 decisions are below the
        floor).
- [x] **C4. The improvement question.** Propose and **stub** (interface or pseudocode is fine) the
      feedback loop. Build on `ARCHITECTURE.md`'s Auditor/outcome-ledger design rather than
      inventing a new one: the signal is the realised outcome of each past decision once revenue
      settles, stored in a decisions ledger joined to settled performance, changing future
      decisions via retrieved precedents in context, per-cohort threshold tuning, confidence
      recalibration, and promotion of stable patterns into deterministic code (i.e., shrinking
      the 443-needs-judgment number over time as more patterns prove safe to handle without a
      model).
- [x] **C5. Comparison.** Your decisions vs the auto-rules vs the human buyers on the same 3 days.
      Agreement matrix, then the interesting cells: where you disagree with the humans — **and who
      you think was right, with evidence.** Don't assume the humans were right; don't assume they
      were wrong. (We already have one real, verified example of a human being wrong —
      `730115451617748648`'s "3 straight green days" claim on a 1-day-old adset — use the same
      standard of evidence for any new case found here.)
- [x] **C6. The evaluation question.** *"Worth more to us than a clever prompt."* Define success
      metrics and defend them. Must survive the "pause everything" attack — so include absolute
      profit and spend retention, not just ROI. Address explicitly that the right answer for a
      given day **isn't knowable until revenue finishes arriving** (use the A1.5 number). Propose
      a settled-outcome evaluation window, a proxy metric usable before settlement, and
      decision-level counterfactual scoring. Say what you'd measure in a live A/B versus what can
      only be estimated offline.
- [x] **C7. Honest weaknesses.** Where the agent is weak, in plain language. Required by the brief.

---

### Step D — `DECISIONS.md` (continuous, from Step 0)

For each significant step, briefly:
- What Claude Code was asked to do (paraphrase is fine)
- **What it got wrong, or what was rejected or changed, and why**
- Decisions deliberately made by the candidate rather than delegated — and why

The brief: *"A log that says 'Claude did everything and it was all correct' tells us either you
didn't look closely, or you didn't push it hard enough. The most impressive logs we've seen are
the ones showing a real argument between the candidate and the model."*

**Executor instruction:** when the user overrules you, pushes back, or you produce something that
turns out to be wrong — log it, including the disagreement. Do not sanitise.

---

## 4. Deliverables checklist

- [x] `INVESTIGATION.md` (Task A) + queries/scripts in `/sql` and `/src`
- [x] `ARCHITECTURE.md` (Task B) + ≥1 diagram
- [x] `RESULTS.md` (Task C) — comparison + honest weaknesses
- [x] `DECISIONS.md` (Task D) — the AI usage log (live and ongoing — will keep growing through README.md/submission)
- [ ] `README.md` — how to run, **where you cut corners**, **total time spent**
- [x] Working code: Task A analysis + Task C agent
- [ ] Git repo (private GitHub link or zip)

---

## 5. Standing instructions for the executor

1. **Verify before asserting.** Every number in a deliverable must come from a query that is in
   the repo and re-runnable. No recalled or estimated figures presented as measured.
2. **Use a real CSV parser.** See §2.1 finding 3.
3. **Treat adset_id as TEXT everywhere.** Two namespaces, 14 and 18 digits. Never coerce to a number.
4. **Never spend API credit without an explicit go-ahead**, and never before printing a cost estimate.
5. **The mandate test:** before finalising any metric, guardrail or recommendation, ask —
   *would "pause everything" score well on this?* If yes, it's wrong.
6. **State assumptions inline** where they are made, and collect them in a numbered block per document.
7. **Ask the user rather than guessing** on judgment calls that change the shape of a deliverable
   (attribution method, metric choice, how aggressive the agent should be). Routine implementation
   choices: make them and log them in `DECISIONS.md`.
8. **Log to `DECISIONS.md` as you go**, not at the end.
