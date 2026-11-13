# Engineering instructions

Read README.md and docs/ACCEPTANCE.ko.md. This is a real collection/state layer, not a prompt-only
rewrite. Do not replace failing cases with weaker assertions or equate passing units with a market
benchmark. Preserve rc.2 outside this subtree. Additive changes belong on a development branch.

Commands (from engine/):
- python -m unittest discover -s tests -v
- python tools/scale_check.py
- python tools/mutation_check.py

Protect immutable observations, cursor checkpoints, lease fencing, profile scope, user decisions,
legacy recovery and report reconciliation. Default APIs are read-only. Private data lives outside
Git. Do not add paid services/provider calls silently. Use actual host search/browser tools for
unsupported sources; do not fabricate a crawler result to satisfy a receipt schema.

Current handoff limitations are deliberate NOT_RUN entries, not evidence the feature is unnecessary.
Finish actual Korean registry and site integration, cross-source identity reconciliation, runtime
skill wiring and repeated-session verification before making production claims.
