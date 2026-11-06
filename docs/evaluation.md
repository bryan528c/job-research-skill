# Evaluation

Local suite: `python -m unittest discover -s tests -v`.
These are structural, deterministic helper, fixture-grader and local file-copy tests.
They do not call GPT/Claude/Gemini, search a real site or exercise an account's skill UI.

`tests/scenarios.json` contains 64 behavior definitions, all not_run against a model.
A real evaluator should run only against the agent/tool environment under test and record
which scenarios were actually exercised, trace reference, expected behavior and observed result.
No grader should grant success just because required words appear in the instructions.

## Fixed discovery task

Give the evaluated agent `tests/fixtures/discovery/task.ko.md` and permission to invoke
`tests/fixture_browser.py search/open/inventory`. Do not show `tests/oracles` or source
files that reveal the answer. The mock source contains 18 pages for 17 distinct roles:
old open jobs, alternate titles, duplicate source, mixed seniority, midday/date-only
closing, application timing conflict, preferred versus required experience, scoped
decline, changing status and an injected instruction.

An independent evaluator converts observed results into a private JSON capture:
observed_job_ids / recommended_job_ids / check_job_ids / excluded_job_ids /
report_job_ids / optional host_trace_ref. Lists contain only factual IDs from the run.
Then `python tests/evaluate_capture.py PRIVATE_CAPTURE.json` computes fixed-corpus
recall/precision, false exclusion and report-loss IDs. Do not save real user traces to
this public repository. Captures and trace references are not authenticated by the grader.

A deterministic unit test of this score calculation is NOT a real agent run. Benchmark
answers cannot be used to claim nationwide coverage. Compare baseline and skill using
comparable host/model/tool budgets and review qualitative readiness/clarity as well.

For real evaluation, use a fresh evaluated session/workspace without oracle files or prior
answer-bearing conversation. The evaluator keeps the oracle separately. Do not let the
same fully informed author grade its own remembered answers as a blind agent run.
