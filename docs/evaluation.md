# Evaluation

Local suite: `python -m unittest discover -s tests -v`.
These are structural, deterministic helper, fixture-grader and local file-copy tests.
They do not call GPT/Claude/Gemini, search a real site or exercise an account's skill UI.

`tests/scenarios.json` contains 64 behavior definitions, all not_run against a model.
The targeted executions in validation/runtime-cases.json are separate from this unexecuted 64-case suite. A real evaluator should run only against the agent/tool environment under test and record
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
The fixture command can append each actual returned output to JSONL when the evaluator sets `JOB_RESEARCH_FIXTURE_TRACE`. Configure this outside the agent prompt.
Then `python tests/evaluate_capture.py PRIVATE_CAPTURE.json --trace PRIVATE_TRACE.jsonl` checks output hashes and opened IDs and computes fixed-corpus
recall/precision, false exclusion and report-loss IDs. Do not save real user traces to
this public repository. Captures and trace references are not authenticated by the grader.

A deterministic unit test of this score calculation is NOT a real agent run. Benchmark
answers cannot be used to claim nationwide coverage. Compare baseline and skill using
comparable host/model/tool budgets and review qualitative readiness/clarity as well.

For real evaluation, use a fresh evaluated session/workspace without oracle files or prior
answer-bearing conversation. The evaluator keeps the oracle separately. Do not let the
same fully informed author grade its own remembered answers as a blind agent run.

## Execution performed for rc.2

Baseline and skill runs started as fresh Work subagent sessions with `fork_turns=none`.
Both used the same synthetic task, source commands and inherited model; no fixed search
quota was imposed. Neither received an answer key or prior answer-bearing conversation.
The task workspaces contained no oracle. This is procedural isolation on a shared
filesystem, not a security sandbox that makes other paths unreadable.

The evaluator read the oracle separately, built captures from the final report, job
decisions and actual fixture command JSONL, and checked the trace against the capture.
Both found 9/9 gold recommendations. The skill run did not improve recall or precision
in this one small corpus. Actual search/open/inventory operations were 47 vs 56; these
are observations, not completion quotas or efficiency claims. The initial report text
was 2,794 vs 1,876 characters, with all actionable roles retained. Selected-job follow-up
operations are excluded from those discovery counts.

Controlled memory-file, no-web/no-memory, selected continuation and real save-failure
cases used synthetic people. One ambiguous `not available` memory field was inconclusive;
a separate new session used an explicit user statement. Do not count it as a pass.
The real-web case searched one employer with a synthetic applicant. It is a tool and
source handling smoke test, not a comprehensive market-quality benchmark. Raw public-web
responses remain outside the release; the release contains hashes and concise findings.
No personal memory, resumes, emails, application outcomes or account traces are included.
