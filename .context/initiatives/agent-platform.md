# Agent platform

Outcome: each VibeStack instance hosts static files and authenticated API/MCP
capabilities that users can extend while building. CLI and web clients use the
same service contract, with chat becoming the primary product interface.

## Feature specifications

These are the user's four requested feature drafts. Edit the linked files;
proposed choices and open decisions are recorded in each. The linked ticket plans
define future work, not completed implementation.

| Specification | Feature | Decisions the specification must resolve |
| --- | --- | --- |
| [SPEC-001](../specifications/SPEC-001-service-host.md) | Extensible service host: static files and authenticated API/MCP | One service process; shared authentication; capability registration; static publish boundary; startup, compatibility and deployment |
| [SPEC-002](../specifications/SPEC-002-rest-api-agent-distribution.md) | REST API, agent guidance and CLI installer URLs | Workspace versus host resources; discovery; versions and errors; stable `/AGENTS.md` and installer contracts; release integrity; client bootstrap and compatibility |
| [SPEC-003](../specifications/SPEC-003-authenticated-mcp.md) | MCP with authentication | Tool/resource coverage; transport; client identity; authorization, revocation and credential lifecycle; relationship to REST; harness compatibility |
| [SPEC-004](../specifications/SPEC-004-chat-agent-interface.md) | Replace existing user interface elements with a service-connected chat agent | User journeys; agent actions and approvals; streaming/results; model/provider decision; recovery and accessibility; onboarding without old controls; transition/removal plan |

See [the specification index](../specifications/README.md) for editing guidance
and integration order. [VST-004](../tickets/VST-004.md) owns the drafting pass.
The service authentication migration and chat replacement change current product/security
boundaries; the existing private desktop and UI remain supported until the
corresponding feature contracts and migration work are implemented.

## Existing foundations

- [VST-001: Codespaces](../tickets/VST-001.md)
- [VST-002: agent access foundation](../tickets/VST-002.md)
- [VST-003: context workflow](../tickets/VST-003.md)

The combined agent-access proposal was removed at the user's request. The four
feature specifications above are the planning entry points; architecture choices
remain draft until resolved in their decision histories.

The public-machine-broker proposal was replaced at the user's request during
SPEC-001 review. Planned tickets VST-005 through VST-007 now cover the service
host and extensions. Historical runner/broker work in VST-002 remains separate.
