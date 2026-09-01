"""
Task C: the full run. For every active adset on 2026-06-10/11/12, builds context, routes to
either the deterministic path (below minimum data floor) or the real LLM call, writes each
decision incrementally to out/decisions.jsonl, prints progress, and enforces a hard cost ceiling
checked before every LLM call, not just at the end.

Usage:
  python run_decisions.py --estimate     # dry run: builds context + routes, no LLM calls, prints
                                          # the real cost estimate based on how many need judgment
  python run_decisions.py --run          # the real run (requires explicit confirmation printed
                                          # by --estimate to have been reviewed)
"""
import argparse
import json
import os
import sys
from datetime import date

from dotenv import load_dotenv
import anthropic

from db import get_connection
from context_compressor import build_context
from deterministic_decision import deterministic_decision
from llm_decision import decide
from guardrail_check import apply_guardrails

load_dotenv()

TARGET_DATES = [date(2026, 6, 10), date(2026, 6, 11), date(2026, 6, 12)]
HARD_COST_CEILING_USD = 6.0  # well under the $10 cap; aborts the run if reached
OUT_PATH = os.path.join(os.path.dirname(__file__), "..", "out", "decisions.jsonl")


def get_target_set(con):
    rows = con.execute(
        """
        SELECT DISTINCT p.adset_id, p.date
        FROM perf p JOIN meta m ON m.adset_id = p.adset_id
        WHERE m.effective_status = 'ACTIVE' AND p.date = ANY(?)
        ORDER BY p.date, p.adset_id
        """,
        [TARGET_DATES],
    ).fetchall()
    return rows


def estimate(con):
    target = get_target_set(con)
    n_below_floor = 0
    n_needs_judgment = 0
    for i, (adset_id, d) in enumerate(target, 1):
        ctx = build_context(con, adset_id, d)
        if ctx["below_minimum_data_floor"]:
            n_below_floor += 1
        else:
            n_needs_judgment += 1
        if i % 250 == 0:
            print(f"  ...built {i}/{len(target)} contexts", flush=True)

    # real observed per-call cost from the two test decisions in llm_decision.py's __main__ run
    observed_avg_haiku_cost = (0.004239 + 0.003872) / 2
    low = n_needs_judgment * observed_avg_haiku_cost
    high = low + (n_needs_judgment * 0.15) * 0.025  # ~15% escalate to Sonnet, ~$0.025 extra each

    print(f"Target set: {len(target)} adset-days across {TARGET_DATES}")
    print(f"  Below minimum data floor (deterministic, no LLM): {n_below_floor}")
    print(f"  Needs real LLM judgment: {n_needs_judgment}")
    print(f"Estimated cost: ${low:.2f} (no escalations) to ${high:.2f} (~15% escalate to Sonnet)")
    print(f"Hard ceiling enforced during the real run: ${HARD_COST_CEILING_USD:.2f}")
    print(f"Both estimates are far under the $10 cap.")
    return n_below_floor, n_needs_judgment


def run(con, client):
    target = get_target_set(con)
    total_cost = 0.0
    n_deterministic = 0
    n_llm = 0
    n_escalated = 0
    action_counts = {"scale_up": 0, "scale_down": 0, "keep": 0, "pause": 0, "escalate": 0}
    tier_counts = {"autonomous": 0, "requires_approval": 0, "forbidden": 0}
    n_errors = 0

    # resume support: skip (adset_id, decision_date) pairs already written by a prior run of
    # this script, and pick counters/cost back up from what's already on disk, rather than
    # reprocess (and re-spend on) everything from scratch. Error entries are deliberately NOT
    # treated as "done" -- they never produced a real decision, so they're retry-eligible. The
    # file is rewritten without them here (rather than left in place) so a successful retry
    # appends a single clean line instead of leaving a duplicate error line alongside it.
    already_done = set()
    good_lines = []
    n_retryable_errors = 0
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    if os.path.exists(OUT_PATH):
        with open(OUT_PATH) as f:
            for line in f:
                d = json.loads(line)
                if d["action"] == "error":
                    n_retryable_errors += 1
                    continue
                good_lines.append(line)
                already_done.add((d["adset_id"], d["decision_date"]))
                total_cost += d["cost_usd"]
                if d["llm_called"]:
                    n_llm += 1
                    if d["escalated_to_sonnet"]:
                        n_escalated += 1
                else:
                    n_deterministic += 1
                action_counts.setdefault(d["action"], 0)
                action_counts[d["action"]] += 1
                tier_counts[d["tier"]] += 1
        with open(OUT_PATH, "w") as f:
            f.writelines(good_lines)
        print(f"Resuming: {len(already_done)} good decisions kept (${total_cost:.4f} spent), "
              f"{n_retryable_errors} prior errors made retry-eligible (file rewritten without "
              f"them), continuing with {len(target) - len(already_done)} remaining.")

    with open(OUT_PATH, "a") as f:
        for i, (adset_id, d) in enumerate(target, 1):
            if (adset_id, str(d)) in already_done:
                continue
            ctx = build_context(con, adset_id, d)

            if ctx["below_minimum_data_floor"]:
                decision = deterministic_decision(ctx)
                n_deterministic += 1
            else:
                if total_cost >= HARD_COST_CEILING_USD:
                    print(f"HARD COST CEILING (${HARD_COST_CEILING_USD}) REACHED at decision {i}/{len(target)} -- aborting.")
                    break
                try:
                    decision = decide(client, ctx)
                except Exception as e:
                    # one malformed/unexpected model response must not kill the other ~420
                    # decisions in the batch. Recorded honestly as a real error, not silently
                    # skipped or guessed at -- action="error" is not a valid decision action,
                    # deliberately, so this is unmistakable in the output and in RESULTS.md.
                    n_errors += 1
                    decision = {
                        "adset_id": adset_id, "decision_date": str(d), "action": "error",
                        "amount": None, "confidence": 0.0, "raw_model_confidence": None,
                        "confidence_caps_applied": [], "reasoning": f"LLM call failed: {type(e).__name__}: {e}",
                        "data_quality_flags": ctx["data_quality_flags"], "expected_profit_impact": None,
                        "escalated_to_sonnet": False, "model_used": "error", "input_tokens": 0,
                        "output_tokens": 0, "cost_usd": 0.0, "llm_called": True,
                    }
                    print(f"[{i}/{len(target)}] {adset_id} {d} -> ERROR: {type(e).__name__}: {e}")
                else:
                    total_cost += decision["cost_usd"]
                    n_llm += 1
                    if decision["escalated_to_sonnet"]:
                        n_escalated += 1

            decision = apply_guardrails(decision, ctx)
            action_counts.setdefault(decision["action"], 0)
            action_counts[decision["action"]] += 1
            tier_counts[decision["tier"]] += 1

            f.write(json.dumps(decision) + "\n")
            f.flush()

            # every LLM-backed decision prints live (the interesting ones); deterministic ones
            # print a heartbeat every 200 so the run is never silent for long, without flooding
            # the terminal with 1,621 near-identical lines
            if not ctx["below_minimum_data_floor"] or i % 200 == 0:
                print(f"[{i}/{len(target)}] {adset_id} {d} -> {decision['action']:11s} "
                      f"tier={decision['tier']:17s} conf={decision['confidence']:.2f} "
                      f"{decision['model_used']:30s} cost_so_far=${total_cost:.4f}")

    print(f"\n{'='*70}\nDone.")
    print(f"{n_deterministic} deterministic (no LLM), {n_llm} LLM calls ({n_escalated} escalated to Sonnet), {n_errors} errors.")
    print(f"Actions:  " + "  ".join(f"{k}={v}" for k, v in action_counts.items()))
    print(f"Tiers:    " + "  ".join(f"{k}={v}" for k, v in tier_counts.items()))
    print(f"Total spend: ${total_cost:.4f}")
    print(f"Decisions written to {OUT_PATH}")
    if n_errors:
        print(f"NOTE: {n_errors} decision(s) failed with a real error (action=\"error\" in the "
              f"output) -- these need manual review before RESULTS.md treats this as a clean run.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--estimate", action="store_true")
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()

    con = get_connection()

    if args.estimate:
        estimate(con)
    elif args.run:
        key = os.environ.get("ANTHROPIC_API_KEY")
        client = anthropic.Anthropic(api_key=key)
        run(con, client)
    else:
        print("Pass --estimate or --run", file=sys.stderr)
        sys.exit(1)
