# Pass 3: execute a development pass

Use with: ticket ID, intended branch/base, and any existing handoff.

> Read root AGENTS.md, .context/workflow.md, the ticket, its specification and
> dependency evidence. Inspect Git status and preserve unrelated work. Confirm
> the current branch manifest owns this ticket, or create an isolated branch
> and manifest from the correct base. Check dependencies and unresolved
> decisions before dependent implementation. Set in_progress and implement
> the bounded ticket, keeping code, docs and ticket evidence together. Run the
> checks appropriate to the change under docs/DEVELOPMENT.md; record failures
> and resolve those within scope. Do not weaken acceptance to get a pass.
> If the scope expands, revise the specification/plan explicitly or add a
> linked follow-up ticket. At the pass boundary, record changes, decisions,
> exact validation results, limitations and the next action. Set in_review
> while required checks remain, blocked only for a concrete blocker, or
> validated when acceptance is complete. A validated branch is not delivered
> until its record and implementation reach main. Push/open/merge/deploy only
> within the user's authorization. Report ticket, branch, PR, checks and state.

Expected output: implemented increment or precise resumable handoff, with no
claim that a proposed tool, pending test, unmerged change or undeployed image is
already available.
