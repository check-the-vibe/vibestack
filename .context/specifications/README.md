# Feature specifications: edit these files

Edit a feature's Markdown file below to change its desired behavior, acceptance
criteria or decisions. Use the sections **Outcome and user journeys**, **Contract**,
**Acceptance criteria** and **Open decisions**. Record meaningful changes in
**Decision history**, then update affected tickets. The template is for creating
new specifications, not the file to edit for these four features.

| ID | File to edit | Focus |
| --- | --- | --- |
| SPEC-001 | [Extensible service host](SPEC-001-service-host.md) | Static files, one authenticated API/MCP process and user-authored capabilities |
| SPEC-002 | [REST API and distribution](SPEC-002-rest-api-agent-distribution.md) | Shared operations, discovery, AGENTS.md and CLI installer URLs |
| SPEC-003 | [Authenticated MCP](SPEC-003-authenticated-mcp.md) | Remote authorization, local adapter and tool coverage |
| SPEC-004 | [Chat agent interface](SPEC-004-chat-agent-interface.md) | Agent icon/chat overlay, host API activation of in-VibeStack providers and complete old-UI removal |

Read design decisions from each specification and implementation/verification
state from its tickets. The draft label preserves unresolved compatibility and
account-dependent decisions; it is not a runtime status. The
[runthrough](../runthrough.md) distinguishes main, candidate branches and deployed
images, including the checks still requiring a human account.

## Review history

All four drafts are checked into main, authored under VST-004. PR #10 was
closed after direct integration at the user's request on 2026-09-21. There is
no separate branch for each specification. Implementation branches are registered
per ticket in the [context index](../README.md).

The specifications were reviewed in this order:

1. [SPEC-002: REST API and distribution](SPEC-002-rest-api-agent-distribution.md): agree on service boundaries, shared operations and agent bootstrap first.
2. [SPEC-001: Extensible service host](SPEC-001-service-host.md): review the simple static/API/MCP topology and capability authoring workflow. The draft has been rewritten around the simpler service requirement.
3. [SPEC-003: Authenticated MCP](SPEC-003-authenticated-mcp.md): expose the agreed operations with the correct authorization.
4. [SPEC-004: Agent overlay and providers](SPEC-004-chat-agent-interface.md): icon/chat interaction, in-VibeStack provider installation/activation and old-UI removal.

SPEC-002 establishes the one-URL guide and shared capability contract. The
implementation pass has reached main and deployed acceptance; follow the
[runthrough](../runthrough.md) for the current review. SPEC-003's direction was
accepted by the user; remaining client/authentication compatibility choices
must be verified explicitly. Keep each
specification draft until its required decisions are resolved. The retired
combined agent-access proposal is no longer a separate design authority.

## Development order

1. Define the small shared capability/registration contract in [VST-008](../tickets/VST-008.md), including one harmless extension example.
2. Build the static host and authenticated service foundation in [VST-005](../tickets/VST-005.md).
3. Add capability authoring in [VST-006](../tickets/VST-006.md), one-URL guidance/CLI distribution in [VST-009](../tickets/VST-009.md), and MCP authentication in [VST-011](../tickets/VST-011.md).
4. Expose registered MCP tools in [VST-012](../tickets/VST-012.md), then verify four-surface parity in [VST-010](../tickets/VST-010.md) and transport compatibility in [VST-013](../tickets/VST-013.md).
5. Build provider activation/adapters and the chat overlay in [VST-014](../tickets/VST-014.md)–[VST-015](../tickets/VST-015.md), then retire the old interface in [VST-016](../tickets/VST-016.md) after its replacement journeys pass.
6. Complete fresh Codespaces and combined extension/deployment acceptance in [VST-007](../tickets/VST-007.md), including the provider/overlay migration. No fleet infrastructure is required. This final integration scope was recorded on 2026-09-22; real sign-in and outside-gateway checks remain explicit requirements.

This is dependency order, not an automatic launch of parallel agents or an
estimate. Each implementation ticket gets an owning branch when it is started.

For new features, copy [the specification template](../templates/specification.md)
and use [the specification prompt](../prompts/specify.md). For a development plan,
use [the planning prompt](../prompts/plan.md); to execute a ticket, use
[the development prompt](../prompts/develop.md). Follow [the workflow](../workflow.md).
