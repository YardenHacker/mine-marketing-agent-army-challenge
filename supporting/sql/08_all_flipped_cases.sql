-- The 11 "looked like a loser at action time, finished the day a winner"
-- cases, in full detail, across all rules -- these are the direct evidence
-- for A3's "rule made a call a competent human wouldn't have made".
SELECT
    re.rule_id,
    re.action_time,
    re.adset_id,
    re.spend_at_action,
    re.today_roi_at_action AS roi_seen,
    p.spend AS final_spend,
    p.revenue AS final_revenue,
    p.roi AS final_roi,
    p.profit AS final_profit,
    m.account_name
FROM rule_exec re
JOIN perf p ON p.adset_id = re.adset_id AND p.date = re.action_date::DATE
JOIN meta m ON m.adset_id = re.adset_id
WHERE re.response = 'SUCCESS'
  AND re.today_roi_at_action < 0
  AND p.roi >= 0
ORDER BY p.profit DESC;
