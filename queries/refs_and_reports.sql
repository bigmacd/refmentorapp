SELECT
    r.firstname,
    r.lastname,
    ARRAY(
        SELECT DISTINCT ms.date::date
        FROM mentor_sessions AS ms
        WHERE ms.mentee = r.id
          AND ms.date >= date_trunc('year', CURRENT_DATE)
          AND ms.date < date_trunc('year', CURRENT_DATE) + INTERVAL '1 year'
        ORDER BY 1
    ) AS report_dates
FROM referees AS r
WHERE EXISTS (
    SELECT 1
    FROM mentor_sessions AS ms
    WHERE ms.mentee = r.id
      AND ms.date >= date_trunc('year', CURRENT_DATE)
      AND ms.date < date_trunc('year', CURRENT_DATE) + INTERVAL '1 year'
)
ORDER BY r.lastname, r.firstname;
