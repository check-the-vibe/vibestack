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

Read state from each specification. These are initial drafts, with proposed
choices and unresolved decisions. No feature implementation is implied.

## Review together

All four drafts are on `codex/vst-004-feature-specifications` (PR #10), owned by
VST-004. There is no separate branch for each specification yet. Implementation
branches will be created when their individual tickets begin.

Review one specification at a time in this order:

1. [SPEC-002: REST API and distribution](SPEC-002-rest-api-agent-distribution.md): agree on service boundaries, shared operations and agent bootstrap first.
2. [SPEC-001: Extensible service host](SPEC-001-service-host.md): review the simple static/API/MCP topology and capability authoring workflow. The draft has been rewritten around the simpler service requirement.
3. [SPEC-003: Authenticated MCP](SPEC-003-authenticated-mcp.md): expose the agreed operations with the correct authorization.
4. [SPEC-004: Agent overlay and providers](SPEC-004-chat-agent-interface.md): review the icon/chat interaction, in-VibeStack provider installation/activation and old-UI removal. This is the current review file.

SPEC-002 establishes the one-URL guide and shared capability contract. The review
is now on SPEC-004. SPEC-003's direction was accepted by the user; its exact
client/authentication compatibility choices remain to be verified. Keep each
specification draft until its required decisions are resolved. The retired
combined agent-access proposal is no longer a separate design authority.

## Development order

1. Define the small shared capability/registration contract in [VST-008](../tickets/VST-008.md), including one harmless extension example.
2. Build the static host and authenticated service foundation in [VST-005](../tickets/VST-005.md).
3. Add capability authoring in [VST-006](../tickets/VST-006.md), one-URL guidance/CLI distribution in [VST-009](../tickets/VST-009.md), and MCP authentication in [VST-011](../tickets/VST-011.md).
4. Expose registered MCP tools in [VST-012](../tickets/VST-012.md), then verify four-surface parity in [VST-010](../tickets/VST-010.md) and transport compatibility in [VST-013](../tickets/VST-013.md).
5. Complete fresh Codespaces and extension/deployment acceptance in [VST-007](../tickets/VST-007.md). No fleet infrastructure is required.
6. Build provider activation/adapters and the chat overlay in [VST-014](../tickets/VST-014.md)–[VST-015](../tickets/VST-015.md), then retire the old interface in [VST-016](../tickets/VST-016.md) after its replacement journeys pass.

This is dependency order, not an automatic launch of parallel agents or an
estimate. Each implementation ticket gets an owning branch when it is started.

For new features, copy [the specification template](../templates/specification.md)
and use [the specification prompt](../prompts/specify.md). For a development plan,
use [the planning prompt](../prompts/plan.md); to execute a ticket, use
[the development prompt](../prompts/develop.md). Follow [the workflow](../workflow.md).
