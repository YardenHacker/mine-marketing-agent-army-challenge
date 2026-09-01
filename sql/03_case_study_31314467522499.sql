-- Is the 06-08 06:30 -> 06-10 12:00 window on account 9913405683583663 a
-- clean outage (100% failure) or a mix? If clean, that's strong evidence of
-- a real, time-bounded token outage rather than a rule-specific bug.
SELECT
    action_time,
    rule_id,
    adset_id,
    response
FROM rule_exec
WHERE account_id = '9913405683583663'
  AND action_time::TIMESTAMP BETWEEN '2026-06-08 06:00:00' AND '2026-06-10 13:00:00'
ORDER BY action_time;

-- full rule_execution history for the R09 case-study adset -- what turned
-- it off in the first place, before R09 tried (and failed) to turn it back on
SELECT action_date, action_time, rule_id, action_name, old_budget, new_budget,
       response, today_roi_at_action, last_3_days_roi_at_action, total_days_at_action
FROM rule_exec
WHERE adset_id = '31314467522499'
ORDER BY action_time;

-- any manual buyer action on this adset during the week?
SELECT action_time, event_type, old_budget, new_budget, note
FROM buyer
WHERE adset_id = '31314467522499'
ORDER BY action_time;

-- full daily performance history for this adset across the whole week --
-- did it actually stay paused (spend=0) through 06-08, and what did it do
-- on days it WAS allowed to run?
SELECT date, spend, revenue, profit, roi, fb_conversions, estimated_conversions, spend_day_no
FROM perf
WHERE adset_id = '31314467522499'
ORDER BY date;

-- metadata for this adset -- current status, budget, campaign naming
SELECT account_name, campaign_name, adset_name, effective_status, delivery_status,
       daily_budget, creation_date
FROM meta
WHERE adset_id = '31314467522499';
