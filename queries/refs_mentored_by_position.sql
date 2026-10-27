WITH year_sessions AS (
    SELECT
        r.id,
        r.firstname,
        r.lastname,
        ms.position
    FROM mentor_sessions AS ms
    JOIN referees AS r
        ON r.id = ms.mentee
    WHERE ms.date >= date_trunc('year', CURRENT_DATE)
      AND ms.date < date_trunc('year', CURRENT_DATE) + INTERVAL '1 year'
),
flags AS (
    SELECT
        id,
        firstname,
        lastname,
        bool_or(position IN ('AR1', 'AR2')) AS mentored_ar,
        bool_or(position = 'Center') AS mentored_center
    FROM year_sessions
    GROUP BY id, firstname, lastname
)
SELECT 'AR only' AS list, firstname, lastname
FROM flags
WHERE mentored_ar AND NOT mentored_center
UNION ALL
SELECT 'Center only', firstname, lastname
FROM flags
WHERE mentored_center AND NOT mentored_ar
UNION ALL
SELECT 'both', firstname, lastname
FROM flags
WHERE mentored_ar AND mentored_center
ORDER BY list, lastname, firstname;
