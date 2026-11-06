# Optional application continuation

This branch runs only when the user selects a job or explicitly requests preparation.
No prompts are generated for all jobs after every search. One optional instruction in
the first/useful report is enough; omit repeated upselling and empty follow-up sections.

## Selection and freshness

Resolve a selection against its report ID and number-to-job-ID mapping. “2번” refers to
that report, not whichever candidate happens to be second now. If multiple referenced
reports or duplicate names make selection ambiguous, ask a short clarification before
carrying facts. Preserve the legal employer, round, role and source identity.
Reopen current official requirements/deadline/apply route when tools allow it; do not
invent refreshed facts if offline. If closed, distinguish already-submitted preparation
from a new application. Never swap to a different round without telling the user.

## Same conversation

Use relevant memory and existing candidate evidence, inspect supplied/current application
questions, and build a short preparation plan: main positioning, relevant examples,
most important gap, real deadline versus proposed target, next practical step. Follow
the user's stage (research, outline, portfolio, draft, interview); do not auto-write a
full cover letter when they only request a plan. Missing application questions/limits
are unknown, not invented. Work can proceed on independent parts.

## Copyable new-chat prompt

Default to plain text in one code block. The destination is not assumed to remember
anything. Include just enough to resume:
- exact employer, role, campaign and selected record ID;
- public posting and application URLs; last observed time and verification limits;
- actual deadline with original precision/timezone, location/type/start date when known;
- dominant duties, essential qualifications, known process and unresolved blockers;
- only relevant user-confirmed/reported career facts and scoped preferences, with dates
  when meaningful; a short original-source/evidence note and role boundaries;
- current submission/preparation status (unknown when unknown), goal and next step;
- revalidate current source facts; never invent achievements, qualifications, questions,
  word limits, acceptance odds or submission status; do not submit or message anyone.

User asking for a transfer prompt authorizes producing a visible minimal draft, not
posting it to another service. Do not include contact details, ID numbers, private
emails, full resumes, unrelated health/family details or the complete memory record.
Use named relevant projects only as the user supplied them, with no invented metrics.
Do not ask for consent for every harmless summary; ask before materially broader sharing.
Keep source links and compact factual evidence, never hidden chain-of-thought.

## Stages and boundaries

User can say “관심”, “이번엔 제외”, “제출했어”, “면접 준비” or “새 채팅용으로 줘”.
Update only the supported, explicit scope; a drafted prompt is not an application.
Support multiple selected jobs with separate identities. If the user has not selected
one, do not guess a favorite or turn follow-up into a prerequisite for receiving results.
