# Optional internal record contract

These formats are helper inputs, not user forms or required host storage. Hosts can use
an equivalent private representation. The optional helper never fetches web pages.

## Serious candidate

Identity: id / legal employer / role / round. Separate recruiting_status(open/closed/unknown),
decision(recommend/check/exclude), user_decision and application_stage. Store checked_at,
source links with kind/status/time, deadline precision and concise factual evidence.
Unknown qualifications and blockers remain explicit. Do not copy all personal memory.
A public-role URL needs source association beyond HTTP success.

## Report

report_id, date_label, conclusion, deadline-ordered jobs with report_number, optional
change_note/limitation/next_action/offer_followup. Number→id mapping is report scoped.
The renderer preserves host ordering rather than inventing times for imprecise deadlines.
All actionable worthwhile jobs stay represented; a retained full list must really exist.

## Coverage receipt

skill_version, scope, branches with observed evidence IDs, observations with timestamps,
older_open/uncertain_exclusions checks, counter_searches and new-fit follow-through,
candidates and their dispositions, displayed/retained job IDs, material gaps/revisit,
stop reason, evidence assurance and save status. Example in tests/fixtures.
A missing plan or unresolved material branch forbids claiming scope complete.

Do not equate this JSON's validity with browsing authenticity. Self-reported IDs need
host trace corroboration for stronger assurance. Do not save hidden reasoning. Records
and traces with real user/job data belong in an authorized private store, not this repo.
