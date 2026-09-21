# Feature specifications: edit these files

Edit a feature's Markdown file below to change its desired behavior, acceptance
criteria or decisions. Use the sections **Outcome and user journeys**, **Contract**,
**Acceptance criteria** and **Open decisions**. Record meaningful changes in
**Decision history**, then update affected tickets. The template is for creating
new specifications, not the file to edit for these four features.

| ID | File to edit | Focus |
| --- | --- | --- |
| SPEC-001 | [Public machine broker](SPEC-001-public-machine-broker.md) | nginx, broker service, machine enrollment/connections and public-client authority |
| SPEC-002 | [REST API and distribution](SPEC-002-rest-api-agent-distribution.md) | Shared operations, discovery, AGENTS.md and CLI installer URLs |
| SPEC-003 | [Authenticated MCP](SPEC-003-authenticated-mcp.md) | Remote authorization, local adapter and tool coverage |
| SPEC-004 | [Chat agent interface](SPEC-004-chat-agent-interface.md) | Chat replacing existing UI, authorized tools and migration |

Read state from each specification. These are initial drafts, with proposed
choices and unresolved decisions. No feature implementation is implied.

## Development order

1. Review the drafts and resolve shared identity, operation and deployment decisions.
2. Start [VST-008](../tickets/VST-008.md), the shared operation/API contract pass.
3. Build enrollment [VST-005](../tickets/VST-005.md), then connector [VST-006](../tickets/VST-006.md).
4. Discovery/installers [VST-009](../tickets/VST-009.md) can proceed after the contract; REST parity [VST-010](../tickets/VST-010.md) follows identity/routing.
5. Broker recovery [VST-007](../tickets/VST-007.md), MCP [VST-011](../tickets/VST-011.md)–[VST-013](../tickets/VST-013.md), and chat [VST-014](../tickets/VST-014.md)–[VST-015](../tickets/VST-015.md) follow their explicit ticket dependencies.
6. Retire the old interface with [VST-016](../tickets/VST-016.md) only after replacement journeys and agent access pass.

This is dependency order, not an automatic launch of parallel agents or an
estimate. Each implementation ticket gets an owning branch when it is started.

For new features, copy [the specification template](../templates/specification.md)
and use [the specification prompt](../prompts/specify.md). For a development plan,
use [the planning prompt](../prompts/plan.md); to execute a ticket, use
[the development prompt](../prompts/develop.md). Follow [the workflow](../workflow.md).
