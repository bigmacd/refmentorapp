SELECT *
FROM mentor_sessions
WHERE date >= date_trunc('year', CURRENT_DATE)
	AND date < date_trunc('year', CURRENT_DATE) + INTERVAL '1 year'
