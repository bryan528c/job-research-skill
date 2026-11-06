# Quick start

Load the native skill through your account's supported import surface, then ask:
“Find worthwhile jobs for me. Use my available career context and keep the report brief.”
The host supplies web access and optional relevant memory. Neither is granted by a ZIP.

Claude upload: `dist/job-research-claude.zip` (one skill folder).
Gemini or root-file import: `dist/job-research-upload-root.zip` (SKILL.md at archive root).
OpenAI plugin packaging: `dist/job-research-openai-plugin.zip`; publication/availability
and workspace permissions are separate from packaging.
CLI hosts: copy `skills/job-research/` into the documented skills directory or run the
optional local installer for just your host. Existing directories are never overwritten.

No native skill support? Attach `portable/JOB_RESEARCH.md` or use its text in supported
custom instructions. This is an instruction fallback, not verified native installation.

Results contain direct role/application URLs. “Prepare job 2 here” continues in the
same chat. “Give me a new-chat prompt for job 2” returns a minimal self-contained brief.
No forced application workflow. Private state stays private; another provider does not
inherit memory. Unknown consequential facts are asked only when necessary.

This RC has been explicitly loaded and exercised in ChatGPT Work, including limited real-web reads. Other host runtimes, native account memory and scheduling remain untested; brief-output consistency is still partial. Read
`docs/validation.md`, `docs/compatibility.ko.md` and `LICENSE-CHOICE.md` before publication.
