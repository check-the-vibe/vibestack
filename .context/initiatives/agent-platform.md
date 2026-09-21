# Agent platform

Outcome: machines and authorized clients can use VibeStack through a coherent
service contract, with a chat agent becoming the primary user interface.

## Feature specifications

These are the user's four requested feature drafts. Edit the linked files;
proposed choices and open decisions are recorded in each. The linked ticket plans
define future work, not completed implementation.

| Specification | Feature | Decisions the specification must resolve |
| --- | --- | --- |
| [SPEC-001](../specifications/SPEC-001-public-machine-broker.md) | Broker service: nginx plus a service accepting machine connections and public-client access | Machine enrollment and identity; outbound connection/reconnection model; routing; client authentication/authorization; isolation; nginx versus application responsibilities; hosting and failure recovery |
| [SPEC-002](../specifications/SPEC-002-rest-api-agent-distribution.md) | REST API, agent guidance and CLI installer URLs | Workspace versus host resources; discovery; versions and errors; stable `/AGENTS.md` and installer contracts; release integrity; client bootstrap and compatibility |
| [SPEC-003](../specifications/SPEC-003-authenticated-mcp.md) | MCP with authentication | Tool/resource coverage; transport; client and machine identity; authorization, revocation and credential lifecycle; relationship to REST; harness compatibility |
| [SPEC-004](../specifications/SPEC-004-chat-agent-interface.md) | Replace existing user interface elements with a service-connected chat agent | User journeys; agent actions and approvals; streaming/results; model/provider decision; recovery and accessibility; onboarding without old controls; transition/removal plan |

See [the specification index](../specifications/README.md) for editing guidance
and integration order. [VST-004](../tickets/VST-004.md) owns the drafting pass.
The public broker and chat replacement change current product/security
boundaries; the existing private desktop and UI remain supported until the
corresponding feature contracts and migration work are implemented.

## Existing foundations

- [VST-001: Codespaces](../tickets/VST-001.md)
- [VST-002: agent access foundation](../tickets/VST-002.md)
- [VST-003: context workflow](../tickets/VST-003.md)
- [Prior API/MCP proposal](../../docs/architecture/agent-access-redesign.md)

The prior proposal is input to the new specifications, not a decision that
preselects the public broker, authentication architecture or chat design.
