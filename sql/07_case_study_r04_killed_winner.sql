-- R04 fired 109 times (51% of all firings) on "Total Days = 1 | budget > 35%
-- | ROI < -50%" -- a same-day, partial-data judgment on brand-new adsets.
-- Find the clearest case: today_roi_at_action was deeply negative (matching
-- R04's own -50% threshold), but the day finished at breakeven or better,
-- with enough spend at stake that this isn't a rounding artifact.
SELECT
    re.action_time,
    re.adset_id,
    re.old_budget,
    re.spend_at_action,
    re.today_roi_at_action,
    p.spend AS final_day_spend,
    p.revenue AS final_day_revenue,
    p.roi AS final_day_roi,
    p.profit AS final_day_profit,
    m.account_name,
    m.adset_name
FROM rule_exec re
JOIN perf p ON p.adset_id = re.adset_id AND p.date = re.action_date::DATE
JOIN meta m ON m.adset_id = re.adset_id
WHERE re.rule_id = 'R04'
  AND re.response = 'SUCCESS'
  AND re.today_roi_at_action < -0.3
  AND p.roi > -0.1
ORDER BY p.spend DESC
LIMIT 10;

-- for the single clearest case, pull its FULL week of performance (was it
-- a one-day blip or did it go on to be a consistently good adset that
-- stayed dead the rest of the week because R04 killed it on day 1?)
