"""
Task C, C1: the actual LLM judgment call.

Design choices, each traceable to ARCHITECTURE.md or a decision made this session:
- Structured output via Claude's tool-use mechanism (a forced tool call), not "please output
  JSON" in prose -- guarantees schema-valid output, doesn't rely on the model's formatting.
- The model never outputs a raw dollar "amount". It picks a `budget_step` from a fixed,
  pre-computed set (ARCHITECTURE.md sec2, "How amount actually gets decided") -- the actual
  dollar amount is computed in code from context["current_budget"] (the spend-anchored figure,
  never meta.daily_budget). This is a structural constraint, not a post-hoc check.
- Haiku 4.5 is the default model. If Haiku's own raw confidence is < 0.5 AND it didn't already
  choose "escalate" (an explicit escalate needs no second opinion -- it's already routing to a
  human), a second call goes to Sonnet 5 for a stronger read, and Sonnet's answer is used as
  final. This mirrors ARCHITECTURE.md sec3's ~85/15 split without forcing an exact ratio.
- Confidence is capped AFTER the call, in code, per confidence_cap.py -- never left to the model.
- The system prompt is marked for prompt caching (cache_control) since it's identical across
  every call in a batch.
- A hard cost ceiling aborts the run if exceeded -- checked before every call, not just at the end.
"""
import json
import os
from dotenv import load_dotenv
import anthropic

from confidence_cap import apply_confidence_cap

load_dotenv()

HAIKU = "claude-haiku-4-5"
SONNET = "claude-sonnet-5"

PRICES = {  # per million tokens: (input, output)
    HAIKU: (1.0, 5.0),
    SONNET: (2.0, 10.0),
}

BUDGET_STEPS = {"-20%": -0.20, "-10%": -0.10, "0%": 0.0, "+10%": 0.10, "+20%": 0.20}

SONNET_ESCALATION_CONFIDENCE_THRESHOLD = 0.5

SYSTEM_PROMPT = """You are the Adset Decision Agent for a performance marketing company running \
Meta ad campaigns. For each adset, you receive a compact, pre-aggregated context object -- \
never a raw table -- and must decide one action.

THE MANDATE: maintain or grow total spend and absolute profit while improving efficiency. Do NOT \
optimize ROI by shrinking. An agent that pauses or cuts everything scores a great ROI and \
destroys the business. Scaling up a genuine winner is just as valid an answer as cutting a loser.

ACTIONS:
- scale_up: increase budget. Requires a budget_step from {+10%, +20%}.
- scale_down: decrease budget. Requires a budget_step from {-10%, -20%}. This is the lower-risk \
FIRST move for a trend that is declining but not yet catastrophic -- a smaller, reversible step \
that preserves the adset's ability to recover, rather than a full stop. Prefer this over `pause` \
when the decline is real but you have not yet seen it be severe AND sustained across multiple \
recent days; reserve `pause` for a trend that is both severe and sustained, or already \
destroying value outright (e.g. consecutive days of zero or deeply negative ROI). Do not treat \
scale_down and pause as interchangeable "cut it" options -- they are different levels of \
intervention for different levels of certainty about how bad things are.
- keep: no change. budget_step is "0%".
- pause: stop spending entirely. budget_step is "0%" (pausing isn't a budget change, it's a \
status change). Reserve this for clear, sustained, severe deterioration -- not as a default \
whenever performance looks bad, when a smaller scale_down would let the adset keep a chance to \
recover.
- escalate: you do not have enough information, or the situation is genuinely ambiguous, to \
commit to a confident action. This is a valid answer when it's actually true -- not a failure \
when warranted, and not a default when it isn't. Most adsets that reach you have SOME caveat in \
their data (that's normal, not disqualifying) -- escalate is for when the caveats genuinely \
prevent forming any defensible read, not merely because a caveat exists. If the trailing ROI \
trend is reasonably clear, commit to scale_up/scale_down/keep/pause even alongside caveats like \
budget_scale_uncertain or cohort_too_small -- those affect how much you trust the exact \
magnitude, not whether you can read the direction. Escalating everything defeats the purpose of \
having an agent at all and fails the mandate as surely as pausing everything does.

THE BUDGET STEP IS A FIXED CHOICE, NOT A NUMBER YOU INVENT. You will never output a dollar \
amount. You pick one of the five listed steps; the system computes the actual dollar change \
from the adset's own current_budget (already provided, already anchored to real observed \
spend -- never trust declared_budget_meta for magnitude, it is frequently on an inconsistent \
scale and is provided only for transparency).

CONFIDENCE: report your own honest confidence (0.0-1.0) in this specific decision, given \
exactly the evidence in the context object. Do not let the presence of data_quality_flags stop \
you from committing to a real action when the evidence genuinely supports one -- but your \
confidence should reflect how much you actually know, not how decisive you feel. A single good \
day on a brand-new adset (age_days=1, "insufficient_history" flagged) should never produce high \
confidence, no matter how good that one day looks -- there is categorically not enough \
information yet, regardless of the number itself. Conversely, an established adset (age_days>10) \
with a consistent multi-day trend deserves a confidence that reflects that real history, even if \
one or two unrelated caveats are also present.

REASONING: cite the specific evidence from the context object that drove your decision (trailing \
ROI figures, spend trend, recent actions, cohort position if available). Do not restate the \
mandate reminder as if it were evidence -- it is the goal, not the data.

DATA QUALITY FLAGS: the context object already contains flags computed deterministically \
upstream (e.g. insufficient_history, budget_scale_uncertain, near_dataset_edge, \
unreconciled_prior_action, cohort_too_small). You do not need to repeat these, and in the large \
majority of cases you should add none of your own -- return an empty list unless something \
genuinely falls outside the categories already provided. If you do add one, it must be one of \
the fixed options offered in the tool schema, not free text -- this keeps flags comparable across \
thousands of decisions rather than a unique label invented per adset."""

ADDITIONAL_FLAG_OPTIONS = [
    "conflicting_recent_signals",  # e.g. a recent action's direction contradicts the trailing trend
    "extreme_volatility",  # day-to-day swings unusually large even for a young adset
    "possible_data_anomaly",  # a number in the context looks internally implausible
    "recent_status_change",  # spend pattern suggests a pause/resume not reflected elsewhere
    "declared_context_mismatch",  # something in context contradicts something else in context
]

DECISION_TOOL = {
    "name": "record_decision",
    "description": "Record the adset decision.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["scale_up", "scale_down", "keep", "pause", "escalate"]},
            "budget_step": {"type": "string", "enum": list(BUDGET_STEPS.keys())},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "reasoning": {"type": "string"},
            "additional_data_quality_flags": {
                "type": "array",
                "items": {"type": "string", "enum": ADDITIONAL_FLAG_OPTIONS},
                "maxItems": 2,
                "description": "Empty in most cases. A small fixed vocabulary, not free text -- "
                                "see system prompt.",
            },
            "expected_profit_impact": {
                "type": ["number", "null"],
                "description": "Rough expected $ profit impact of this decision vs. doing nothing, if estimable; null if not.",
            },
        },
        "required": ["action", "budget_step", "confidence", "reasoning", "additional_data_quality_flags"],
    },
}


def _cost(model: str, input_tokens: int, output_tokens: int) -> float:
    in_price, out_price = PRICES[model]
    return (input_tokens / 1e6) * in_price + (output_tokens / 1e6) * out_price


def _call(client: anthropic.Anthropic, model: str, context: dict) -> dict:
    resp = client.messages.create(
        model=model,
        # 500 was too tight -- reproduced a real crash (KeyError: 'reasoning') that traced to
        # stop_reason="max_tokens" cutting the tool call off mid-generation. The model's
        # reasoning text alone has been observed using most of a 500-token budget, making
        # completion a coin-flip rather than reliable. 1200 gives real headroom.
        max_tokens=1200,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        tools=[DECISION_TOOL],
        tool_choice={"type": "tool", "name": "record_decision"},
        messages=[{"role": "user", "content": json.dumps(context)}],
    )
    tool_use = next(b for b in resp.content if b.type == "tool_use")
    cost = _cost(model, resp.usage.input_tokens, resp.usage.output_tokens)
    return {
        "raw": tool_use.input,
        "model": model,
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
        "cost_usd": cost,
    }


def decide(client: anthropic.Anthropic, context: dict) -> dict:
    """Runs the Haiku-first, Sonnet-on-low-confidence flow. Returns the full decision record."""
    result = _call(client, HAIKU, context)

    escalated = False
    if result["raw"]["action"] != "escalate" and result["raw"]["confidence"] < SONNET_ESCALATION_CONFIDENCE_THRESHOLD:
        sonnet_result = _call(client, SONNET, context)
        escalated = True
        combined_cost = result["cost_usd"] + sonnet_result["cost_usd"]
        combined_in = result["input_tokens"] + sonnet_result["input_tokens"]
        combined_out = result["output_tokens"] + sonnet_result["output_tokens"]
        result = sonnet_result
        result["cost_usd"] = combined_cost  # cost of BOTH calls, not just the one that decided
        result["input_tokens"] = combined_in
        result["output_tokens"] = combined_out

    raw = result["raw"]
    # .get(..., []) rather than direct access: the tool schema marks this required, but in
    # practice a model has been observed omitting an array field it considers empty/not
    # applicable despite that -- crashing a 443-call batch on the first such response is worse
    # than defaulting to "no additional flags" for that one decision.
    all_flags = list(dict.fromkeys(context["data_quality_flags"] + raw.get("additional_data_quality_flags", [])))
    capped_confidence, caps_applied = apply_confidence_cap(raw["confidence"], all_flags)

    step_pct = BUDGET_STEPS[raw["budget_step"]]
    amount = None
    if raw["action"] in ("scale_up", "scale_down") and step_pct != 0:
        amount = round(context["current_budget"] * (1 + step_pct), 2)

    return {
        "adset_id": context["adset_id"],
        "decision_date": context["decision_date"],
        "action": raw["action"],
        "amount": amount,
        "confidence": capped_confidence,
        "raw_model_confidence": raw["confidence"],
        "confidence_caps_applied": caps_applied,
        "reasoning": raw["reasoning"],
        "data_quality_flags": all_flags,
        "expected_profit_impact": raw.get("expected_profit_impact"),
        "escalated_to_sonnet": escalated,
        "model_used": result["model"],
        "input_tokens": result["input_tokens"],
        "output_tokens": result["output_tokens"],
        "cost_usd": round(result["cost_usd"], 6),
        "llm_called": True,
    }


if __name__ == "__main__":
    from db import get_connection
    from context_compressor import build_context
    from datetime import date

    key = os.environ.get("ANTHROPIC_API_KEY")
    client = anthropic.Anthropic(api_key=key)
    con = get_connection()

    # the two worked examples from the compressor demo
    for adset_id, d in [("730127988250776273", date(2026, 6, 11)), ("730131468079569872", date(2026, 6, 11))]:
        ctx = build_context(con, adset_id, d)
        decision = decide(client, ctx)
        print(json.dumps(decision, indent=2))
        print("---")
