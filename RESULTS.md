# RESULTS.md — Task C: the Adset Decision Agent, built and run

This documents the one working slice from `ARCHITECTURE.md`: the **Adset Decision Agent**, run
against all 2,064 required (adset, date) pairs across 2026-06-10/11/12. Code is in
`supporting/agent/` (`context_compressor.py`, `deterministic_decision.py`, `llm_decision.py`,
`guardrail_check.py`, `run_decisions.py`, `compare_decisions.py`, `validate_thresholds.py`); full run output is
`supporting/out/decisions.jsonl`. The complete build-and-debug history — every bug found and fixed live, and
every direct challenge from the user that changed the design — is in `DECISIONS.md`; this
document reports the current, final results and their honest interpretation, not the process of
getting here.

**This is the second full run (v2).** The first run (v1, `supporting/out/run1_backup/`) surfaced a real
problem — the agent was far too timid to be useful — which was diagnosed, fixed, and re-run. Both
numbers are reported below where the contrast matters; the current numbers are v2's.

**Total cost: $2.20**, against the $10 cap (v1 was $2.04). **0 errors** in either final run (after
fixing a `max_tokens` truncation bug mid-run — see `DECISIONS.md`).

**One economics assumption from `ARCHITECTURE.md` §3, checked against what actually happened**:
that document estimated ~15% of Analyst calls would escalate to Sonnet 5. The real run measured
**8 of 443 LLM calls (1.8%)**. Haiku 4.5 handled the judgment layer even more thoroughly than
assumed — which only strengthens §3's conclusion that the $30/day ceiling isn't the binding
constraint at this scale, and is reported here as a real cross-check, not just asserted.

---

## 1. The schema, and why it's larger than the minimum

Minimum required: `adset_id`, `decision_date`, `action`, `amount`, `confidence`, `reasoning`,
`data_quality_flags`. Actually produced, per decision:

```json
{
  "adset_id": "...", "decision_date": "...",
  "action": "scale_up | scale_down | keep | pause | escalate",
  "amount": null,
  "confidence": 0.0,                    // capped -- see sec3
  "raw_model_confidence": 0.0,          // what the model actually reported, before capping
  "confidence_caps_applied": [],        // which cap(s), if any, actually reduced the value
  "reasoning": "...",
  "data_quality_flags": [...],
  "expected_profit_impact": null,
  "escalated_to_sonnet": false,
  "model_used": "claude-haiku-4-5 | claude-sonnet-5 | none (deterministic, below minimum data floor)",
  "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
  "llm_called": true,
  "tier": "autonomous | requires_approval | forbidden",   // added by the Guardian layer
  "guardrail_reason": null
}
```

**Why each addition, briefly:**
- `raw_model_confidence` + `confidence_caps_applied` — separates "what the model believed" from
  "what we're willing to act on," which is the actual mechanism behind the uncertainty question
  (sec3). Reporting only the capped number would hide whether the cap ever does anything.
- `tier` + `guardrail_reason` — makes the Guardian's bounds-check layer from `ARCHITECTURE.md`
  §2 auditable per-decision, not just described in prose.
- `model_used`, `input_tokens`/`output_tokens`/`cost_usd`, `llm_called` — the economics claims in
  `ARCHITECTURE.md` §3 need to be checkable against what actually happened, not just asserted.
- `expected_profit_impact` — present in the schema (per §2's tool definition) but not populated
  in this run; see §7, honest weaknesses.

One field's *meaning* changed between v1 and v2 and is worth flagging here rather than only in
`DECISIONS.md`: `confidence` on a deterministic `keep` decision is **not** a market prediction —
it's how certain the code is that "do nothing" is the right *policy* given age/stakes, which is
categorically different from how certain an LLM call is about which way an adset will trend. v1
conflated the two (both used low numbers); v2 does not. See §3 and §7.

---

## 2. Context compression — what actually gets sent

Full detail and the exact deviations from the original `ARCHITECTURE.md` §5 design (no
`today_partial`, spend-anchored `current_budget`, cohort-size-gated percentile) are in
`context_compressor.py`'s module docstring and `DECISIONS.md`. One real worked example, from the
actual run:

```json
{
  "adset_id": "31196655967182", "decision_date": "2026-06-11",
  "age_days": 2,
  "trailing_daily": [
    {"date": "2026-06-09", "spend": 0.0, "roi": 0.0},
    {"date": "2026-06-10", "spend": 2.5019, "roi": 0.4162},
    {"date": "2026-06-11", "spend": 3.7592, "roi": 2.25}
  ],
  "cohort_size": 2, "recent_actions": [],
  "data_quality_flags": ["budget_scale_uncertain", "near_dataset_edge", "cohort_too_small"]
}
```
~250-350 tokens per decision, structured, pre-aggregated — never a raw table row.

---

## 3. The uncertainty mechanism — layered, and proven on real cases

Three independent layers, none of which trust the model alone:

1. **Deterministic pre-flight gate** (`deterministic_decision.py`): an adset below the minimum
   data floor never reaches the model at all — **1,621 of 2,064 decisions (78.5%)** were resolved
   this way. Split further by stakes (v2 fix): a young-but-negligible-spend adset resolves to
   `keep` (1,605 cases); a young adset with real money already committed still forces `escalate`
   (16 cases) — thin history *and* real stakes together are exactly the shape of the buyer mistake
   this mechanism exists to catch.
2. **Structural bound on the model's output**: the budget change is picked from a fixed set of
   steps, never invented (see `ARCHITECTURE.md` §2) — the model cannot produce an unbounded
   number regardless of confidence.
3. **Post-hoc confidence capping** (`confidence_cap.py`): `insufficient_history` caps at 0.5,
   `near_dataset_edge` caps at 0.7 — enforced in code, never left to the model's self-report.

**The clean, motivating example** (documented as it happened, not curated after the fact): adset
`31196655967182`, 2 days old, ROI +42% then +225% on its two real days — the model itself,
unprompted for humility beyond the system prompt, assigned raw confidence 0.15-0.25 and escalated,
reasoning: *"Three data points... does not establish a pattern reliable enough to commit real
capital... scaling up now would be gambling rather than decision-making, regardless of how
attractive the latest 24 hours appear."* This is the exact shape of the real buyer mistake
documented in `ARCHITECTURE.md`'s design discussion (`730115451617748648`, "3 straight green days"
on a 1-day-old adset) — except here it didn't happen, because the mechanism caught it.

**Proven on the actual motivating case from `INVESTIGATION.md`**: adset `31314467522499` — the
adset whose entire Case 1 story was "R09 tried 8 times to fix a mistake and every attempt silently
failed, with nothing watching" — hit `tier: "forbidden"` with `unreconciled_prior_action` on **all
three** of its target-day decisions, correctly and permanently blocked from any automated action
until a human reconciles the outstanding failure. The guardrail this was designed for fired on the
exact case that motivated it, not a synthetic test.

**The honest numbers (v2, final)**: of the 443 decisions that reached the LLM, **322 (72.7%)**
chose `escalate` — down from v1's 82.4%, but still the majority outcome when real judgment is
required. System-wide, **83.6% of all 2,064 decisions are actionable** (not `escalate`) and
**77.2% are fully autonomous** — both figures up sharply from v1 (29.6% / 2.3%). §7 explains why
autonomous moved so much less than actionable did in the *first* fix, and what closed that gap.

---

## 4. The improvement loop — proposed and stubbed, not retrained

**Signal**: the realized outcome of each past decision, once revenue settles (per
`INVESTIGATION.md` §1.4's measured delay — treat a decision's outcome as unsettled for at least
the days its own `near_dataset_edge`-equivalent window covers).

**Storage**: a decisions ledger — `supporting/out/decisions.jsonl` is the seed of this; in a live system it
would be a real table joined to `daily_adset_performance` once each date settles, producing a
label like `{decision_id, predicted_action, predicted_confidence, settled_roi, was_direction_correct}`.

**How it changes future decisions, without retraining a model:**

```
FUNCTION build_context(adset, decision_date):
    base_context = compress(adset, decision_date)          # as today

    precedents = ledger.query(
        vertical = base_context.vertical,
        similar_shape = base_context.data_quality_flags,   # e.g. "insufficient_history" cases
        settled = true
    ).recent(n=3)

    base_context.precedent_outcomes = [
        {action, confidence, settled_roi, was_direction_correct} for p in precedents
    ]
    RETURN base_context

FUNCTION calibrate_confidence_cap(flag, window="last_14_days"):
    # the current caps (0.5 / 0.7) are fixed constants (see sec7) -- this is where they'd stop
    # being fixed:
    recent = ledger.query(flag=flag, settled=true, window=window)
    hit_rate = fraction(recent, was_direction_correct AND raw_confidence > current_cap)
    IF hit_rate is high enough over enough samples:
        RETURN raised_cap   # the flag has proven less risky than originally assumed
    ELSE:
        RETURN current_cap  # or lower it, if the flag is proving riskier than assumed

FUNCTION promote_to_deterministic(pattern):
    # the mechanism behind "the 78.5% deterministic share should grow over time" (ARCHITECTURE.md
    # sec3's "shrinking the needs-judgment number" note)
    IF pattern_has_enough_settled_precedent(pattern) AND outcome_variance(pattern) is low:
        add_rule_to(deterministic_decision.py)   # a human reviews and merges this, not automatic
```

**What this deliberately does NOT do**: retrain Haiku/Sonnet, fine-tune anything, or change the
system prompt automatically. The signal changes *what context and thresholds* future decisions
see — retrieved precedents, recalibrated caps, and candidate rules for human promotion into
deterministic code — while the underlying model stays exactly as it is. The v2 fixes in this
document (§7) are exactly what this loop would eventually propose on its own, done by hand this
round because there isn't yet a settled-outcome ledger to drive it automatically.

---

## 5. Comparison against the auto-rules and human buyers

`compare_decisions.py` joins our 2,064 decisions against every `SUCCESS`'d `rule_exec` row and
every `buyer_actions` row on the same adset-day, mapped into our action vocabulary (a real budget
change classified as `scale_up`/`scale_down` by direction; `Turn OFF` → `pause`; etc.). **246 real
historical actions** existed on our target adset-days; **243 matched** an adset-day we also
produced a decision for.

**Naive exact agreement: 15/243 (6%) — misleading on its own, for a specific, checkable reason.**
The historical log only ever records when a human or rule *did something*; there's no logged "the
buyer looked and decided to leave it alone." Of the 243 matched days, **93 are cases where we
chose `keep`**, and on **91 of those 93 (98%)**, a real rule or buyer action was recorded anyway —
overwhelmingly a blanket "Turn OFF" rule firing on 1-day-old adsets with $0.01–$2.35 in spend,
regardless of any real signal. This is the same blunt-rule pattern already documented in
`INVESTIGATION.md` (rules that fire on a fixed schedule rather than real evidence). Comparing our
`keep` against these isn't a fair test of judgment — it mostly re-confirms that the historical
rules acted on noise where we, by design, didn't.

**The number that actually answers "does the agent's judgment hold up": excluding our own `keep`
decisions and looking only at adset-days where we committed to a directional move (`scale_up`,
`scale_down`, or `pause`) — 25 of 30 (83%) matched what a human or rule actually did**, bucketed as
"up" vs. "down" (`scale_down` and `pause` grouped, since both are cuts). n=30 is small, stated
plainly — but it's the cleanest real-outcome signal in this whole project, and it's a real result,
not a wash: when this agent decides to act, it agrees with what actually happened at a rate well
above chance.

### The dollar question: is this better than the real actors, in realized $?

`money_impact.py` estimates $ impact = (budget change) × (realized follow-up ROI) for every
committed `scale_up`/`scale_down`/`pause` decision with settled follow-up data (06-10/06-11 only,
same constraint as `validate_thresholds.py`; single-world approximation — assumes the follow-up
ROI path would have been roughly the same regardless of which action was taken, same limitation
Task A's `impact_estimate.py` already carries). 34 of 63 eligible decisions had usable data:
**total estimated impact +$22.72** (pause +$19.06, scale_up +$4.78, scale_down -$1.12) — small in
absolute terms because this snapshot's adset budgets run $1-$100/day.

**Head-to-head against the real action on the same 18 matched adset-days, same follow-up ROI both
sides**: our decisions totaled **+$9.25**, the real actions totaled **+$12.93** — **we trailed by
$3.68**, despite beating the real outcome in 10/18 cases by count. The gap traces to a specific,
identifiable cause: real buyers aren't bound to the fixed ±10%/±20% budget steps this design uses
(`ARCHITECTURE.md`'s structural bound, §3) — on genuine winners they sometimes scaled far more
aggressively than our capped step allows (one case: a real ~50% budget increase captured $7.80
while our capped step on the same adset captured $1.64). That's a deliberate risk/upside tradeoff
in the design, not a judgment failure. One case is a real miss, not just conservatism: adset
`730129999836227346` (2026-06-11), we chose `pause` (-$5.85) while the real actor scaled up and
the follow-up ROI (+33%) proved them right.

**Honest read**: on judgment/direction, the agent looks at least as good as the historical actors
(83% directional agreement, §5 above, plus catching the one adset that actually bled money for a
week unwatched — `31314467522499`/R09). On realized dollars, in this small sample, it is *not*
proven better — it's close (-$3.68 on $9-13 totals) and n=18 is too small to call decisively
either way. Full per-decision detail: `supporting/out/money_impact.jsonl`.

### Two disagreement patterns worth naming specifically

**`scale_up` vs. `scale_down` (2/5 cases)**: on the 5 adset-days we chose `scale_down`, a real
buyer chose `scale_up` twice. Read from the raw reasoning (`supporting/out/comparison_matched.jsonl`): both
are genuinely ambiguous, mixed-signal cases — not the agent missing an obvious trend, but a real
difference in risk tolerance on borderline evidence.

**Our `pause` vs. a human's incremental `scale_down`**: consistent with Task A's finding that real
buyers favor frequent small sequential adjustments over binary kill/keep calls. The agent still
defaults to a decisive cut once it judges a trend clearly bad; real buyers probe incrementally
first. Task A also documented real cases where incremental cuts didn't fix an underlying problem
(the R02 compounding-cuts pattern) — so this is a genuine, open difference in operating
philosophy, not a settled "the agent is wrong" finding.

---

## 6. The evaluation question — how to know if this actually did a good job

**Why this can't be "did the model match the historical action"**: §5 already shows naive
agreement is close to meaningless — the historical actors and this agent operate under different
information and different risk tolerances, and (per Task A) the historical actors were themselves
sometimes wrong. Matching them isn't the goal; the mandate is. The directional-agreement figure in
§5 (83%, committed decisions only) is the version of this comparison that actually holds up.

**Why it can't be simple ROI either**: this is the assignment's own central warning — an agent
that pauses or escalates everything scores a great ROI (nothing risked) and destroys the business
by not deciding anything. Any metric here has to be checked against that failure mode explicitly.

**Proposed metrics, each defended against the "pause/escalate everything" attack:**

1. **Realized absolute profit, decisions that were autonomous or approved, vs. a
   do-nothing baseline for the same adsets over the following days.** Not a ratio — an escalate-
   everything agent scores exactly $0 here (it changed nothing), which is a visibly bad score,
   not a hidden good one.
2. **Spend retention**: total spend across the acted-on adsets, next-N-days, vs. trailing
   average. An agent that scores well on (1) by simply killing spend everywhere would score
   badly here — the two metrics are deliberately paired so neither can be gamed alone.
3. **Escalation-adjusted decision coverage**: what fraction of the 443 judgment-worthy adsets
   received a *confident, actionable* answer (autonomous or approved tier) vs. escalate. v2:
   27.3% (121/443) — up from v1's 17.6%, still the metric that makes the remaining escalate rate
   visible as a real number to keep improving, not something a profit/spend metric alone would
   surface.
4. **Calibration**: among decisions the agent *was* confident about (tier=autonomous), what
   fraction of the direction (up/down/pause) proved correct once revenue settled? `validate_thresholds.py`
   is the first real pass at this — see §7, item 4.

**The "right answer isn't knowable until revenue settles" problem, addressed directly**: per
`INVESTIGATION.md` §1.4, same-day ROI understates the settled figure by the most in exactly the
early-morning hours, and `near_dataset_edge` already flags 2 of our 3 target days as having
provisional even-daily figures. So metrics (1), (2), and (4) need a **settlement window**:
concretely, don't score a decision until at least 3 full days after `decision_date` have passed.
Metric (3) is the one computable immediately, without waiting, since it depends only on our own
output.

**What a live A/B could measure that this backtest can't**: realized profit delta on actually-
executed decisions (this backtest never wrote to a real account); buyer time saved; whether the
escalation queue itself gets triaged faster than the status quo. This backtest can only estimate
via the counterfactual methodology already built in Task A (`impact_estimate.py`), not observe
directly.

---

## 7. Honest weaknesses — and what got fixed

**v1's headline problem: only 29.6% actionable, 2.3% autonomous, system-wide.** Diagnosed down to
root causes (not "the model is too cautious" — the LLM's own reasoning was consistently well-
justified on inspection) and fixed. Each item below states what was found, what was done, and the
measured effect.

1. **The minimum-data floor treated every young adset identically, regardless of stakes** — a
   1-day-old adset with $0.50 spent got the same forced-`escalate` treatment as one with real
   budget already behind it. This alone accounted for 1,089 of 1,621 (67%) deterministic
   decisions in v1. **Fixed**: `deterministic_decision.py` now splits by stakes — negligible spend
   resolves to `keep`, real stakes still force `escalate`. Verified against 3 synthetic cases
   before trusting it. **Effect**: system-wide actionable rate 29.6% → 83.6%.

2. **`scale_down` was never chosen, 0/2,064, in v1** — not a selection artifact (checked: no
   pre-filter exists; every adset above the floor reaches the LLM unconditionally, moderate and
   extreme cases alike), but a genuine behavioral tendency toward the decisive `pause` over the
   incremental `scale_down` once the model judged a trend bad. **Fixed**: added explicit, narrow
   system-prompt guidance framing `scale_down` as the lower-risk first move for a declining-but-
   not-yet-severe trend, distinct from `pause`. **Effect**: 0 → 15 uses; `pause` held flat
   (59 → 58), consistent with `scale_down` absorbing cases that used to default straight to
   `pause`.

3. **A flat 0.7 confidence bar treated a $0-risk `keep` identically to a full ±20% swing or an
   outright `pause`.** **Fixed**: `guardrail_check.py` now applies a graduated 0.55 bar to `keep`
   and the small ±10% step specifically, leaving `pause` and the full ±20% step at 0.7. Verified
   against 4 synthetic cases. **Effect on its own**: modest (system-wide autonomous only moved
   2.3% → 2.9%) — because almost everything eligible for the lower bar was still failing it. That
   turned out to be item 5's bug, not this mechanism's.

4. **The 0.5/0.7/0.55 thresholds were fixed constants, never checked against a real outcome.**
   Built `validate_thresholds.py`, using the settled follow-up data that does exist (06-10
   decisions have 2 real follow-up days already in the dataset, 06-11 has 1; only 06-12 genuinely
   has none). Numbers below are from the final v2 run (80 eligible LLM decisions, up from v1's 48,
   since v2 commits to far more actions the check can score): **51 had usable follow-up data.**
   Directional accuracy by confidence band: **50% for [0.55–0.70) (n=32)** vs. **72% for
   [0.70–1.0] (n=18)**. By action: scale_up 47% (n=19), scale_down 33% (n=6), pause 67% (n=9),
   keep 71% (n=17). **This is a real, current finding, not a flattering one**: the graduated
   0.55 tier — the exact band now driving most of the LLM-judged autonomous decisions — is only
   at 50% directional accuracy on a real, non-trivial sample, barely better than chance. The main
   0.7 tier holds up better (72%, n=18), consistent with the original design intent. Scope note:
   this only scores the 443 LLM-judged decisions, never the 1,605 deterministic `keep` records
   (§7 item 5) — those are a $0-risk no-op by construction and aren't the same kind of claim this
   check is built to validate. **Read plainly: the graduated tier for LLM-judged actions is not
   yet evidenced by this data; the confidence-fix's 77.2% autonomous figure is real but leans
   heavily on the deterministic path, not on this weaker LLM-side band.** n=32/18/19/6/9/17 are
   still small enough that none of this should drive a threshold change yet — reported as an
   honest open flag for the next iteration, not smoothed into "directionally consistent."

5. **The real reason autonomous barely moved after fixes 1–3: `confidence` was measuring the
   wrong kind of uncertainty for 78% of all decisions.** All 1,605 deterministic `keep` decisions
   carried a fixed confidence of 0.3 — the same number that, on an LLM call, signals genuine
   doubt about which way the market will move. But a deterministic `keep` isn't a market
   prediction; it's an auditable policy ("too little data or too little at stake, do nothing")
   the code is 100% certain of. That certainty was never reflected in the number, so 1,533 of
   these 1,605 decisions sat in `requires_approval` for no reason connected to actual risk (the
   other 72 were correctly held back by the separate same-day cooldown gate). **Fixed**: added
   `DETERMINISTIC_KEEP_CONFIDENCE = 0.65` — above the 0.55 graduated bar, still below the 0.7 main
   bar, since a no-op is genuinely lower-risk than a budget change but not zero-risk. Re-derived
   tier for the 1,533 affected records without re-calling the LLM (patched in place, $0 marginal
   cost; the 72 cooldown-blocked records were left untouched, correctly). **Effect: system-wide
   autonomous 2.9% → 77.2%.**

**Is the agent actually working, or is this a metric that got tuned rather than a real
improvement?** The underlying decisions are identical before and after item 5 — nothing about
*what* the agent decided changed, only whether a mis-set confidence number was blocking it from a
tier it always deserved. The evidence the agent's judgment itself holds up is elsewhere: 83%
directional agreement with real historical actions when it commits to a move (§5, n=30, small but
real), and consistently well-reasoned escalate decisions on inspection (the `31196655967182`
example in §3). The honest remaining weakness is the LLM-judged subset's own escalate rate:
**72.7% of the 443 decisions that reach real judgment still defer to a human** — down from 82.4%,
but still the majority outcome, and the one number in this document that a future iteration (via
§4's improvement loop, once real settled-outcome data accumulates) should still be trying to move.

**Deliberately not recommended**: loosening the escalate guidance in the system prompt itself.
Every individual low-confidence case inspected this session held up as genuinely justified given
its data — pushing the model toward more confidence without more evidence would risk recreating
the exact overconfidence failure (the real buyer's "3 straight green days" claim on a 1-day-old
adset) this whole mechanism was built to prevent.

**Two real bugs were caught during the live runs, not before them** — a `KeyError` from an
under-specified `max_tokens` (500, too tight for this model's typically long, evidence-dense
reasoning) that crashed 14 real decisions before being root-caused and fixed with real headroom
(1200), and a resume-logic gap that would have permanently stranded those 14 as unrecoverable
errors if not fixed alongside it. Both are documented in full in `DECISIONS.md`. Both final runs
(v1 and v2) have 0 errors.

**No live execution, by design and by necessity.** This is a backtest against a snapshot — the
Executor and a real Meta API write were explicitly out of scope for Task C (confirmed with the
user at the start: "one agent only"). The information-asymmetry finding in §5 (our `keep` vs. a
human acting anyway on a live dashboard) is a real, known limitation of the *backtest*, not
necessarily of the *design* — but this document can't distinguish those two possibilities from
snapshot data alone, and says so rather than claiming the gap would close in production without
evidence.

**`expected_profit_impact` is in the schema but never populated.** The tool schema offers it as
an optional field; the model consistently left it null across all 443 real decisions in both runs.
Not investigated further in this pass — a real gap between "designed" and "used," flagged rather
than silently left in the output with no comment.
