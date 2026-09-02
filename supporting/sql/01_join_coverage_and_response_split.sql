-- A1.2: how well does rule_executions.adset_id join to perf and meta?
-- A1.3: split executions by response status -- only SUCCESS actually changed
--       anything in the live system. Treating the whole log as "what happened"
--       would be wrong: 30 rows are logged Meta API errors (access token
--       invalidated) and 20 are "No budget to change" no-ops.

-- join coverage
SELECT
    count(*) AS total_executions,
    count(DISTINCT re.adset_id) AS unique_adsets,
    count(DISTINCT p.adset_id) AS matched_in_perf,
    count(DISTINCT m.adset_id) AS matched_in_meta
FROM rule_exec re
LEFT JOIN (SELECT DISTINCT adset_id FROM perf) p ON p.adset_id = re.adset_id
LEFT JOIN (SELECT DISTINCT adset_id FROM meta) m ON m.adset_id = re.adset_id;

-- response status split
SELECT
    CASE
        WHEN response = 'SUCCESS' THEN 'SUCCESS'
        WHEN response LIKE '%No budget to change%' THEN 'NO_OP (no budget to change)'
        WHEN response LIKE '{%error%' THEN 'FAILED (API error)'
        ELSE 'OTHER: ' || response
    END AS response_category,
    count(*) AS n
FROM rule_exec
GROUP BY 1
ORDER BY n DESC;

-- what do the failed rows actually contain? (sanity check the parser handled
-- the embedded commas/JSON in `response` correctly -- rule_id should always
-- be R01..R12, never a stray fragment of the JSON error message)
SELECT DISTINCT rule_id FROM rule_exec ORDER BY rule_id;

-- distribution of response by rule -- are failures/no-ops concentrated in
-- specific rules, or spread evenly?
SELECT
    rule_id,
    count(*) FILTER (WHERE response = 'SUCCESS') AS success,
    count(*) FILTER (WHERE response LIKE '%No budget to change%') AS no_op,
    count(*) FILTER (WHERE response LIKE '{%error%') AS failed,
    count(*) AS total
FROM rule_exec
GROUP BY rule_id
ORDER BY total DESC;
