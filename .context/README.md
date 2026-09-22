# Project context and work tracking

Start here, then read [the operating instructions](workflow.md). This is a
Git-native system: Markdown records travel with the code they describe.

## Hierarchy

```text
.context/
  README.md                    navigation, not a duplicate status board
  workflow.md                  operating rules and Git state semantics
  github-codespaces.md          environment-specific guidance
  initiatives/                 outcomes and feature queues
  specifications/              feature contracts and project plans
  tickets/                     bounded work, progress and evidence
  branches/                    branch-to-ticket manifests
  templates/                   specification, ticket and branch templates
  prompts/                     specification, planning and development passes
```

An initiative groups specifications. A specification defines a feature and its
ordered ticket plan. A ticket belongs to one specification (or is explicitly a
bootstrap/imported exception). A branch manifest lists at least one ticket and
exactly one primary ticket. Prefer one bounded ticket per branch.

## Start points

- [Deployed Codespace and user verification runthrough](runthrough.md)
- [Agent platform initiative and feature drafts](initiatives/agent-platform.md)
- [Specification directory](specifications/README.md)
- [Specification-writing prompt](prompts/specify.md)
- [Project-planning prompt](prompts/plan.md)
- [Development-pass prompt](prompts/develop.md)
- [Specification template](templates/specification.md)
- [Ticket template](templates/ticket.md)
- [Branch manifest template](templates/branch.md)

## Registered work

| Ticket | Scope | Branch manifest |
| --- | --- | --- |
| [VST-001](tickets/VST-001.md) | Existing Codespaces startup PR | [VST-001](branches/VST-001.md) |
| [VST-002](tickets/VST-002.md) | Existing broker/access foundation and source mount PR | [VST-002](branches/VST-002.md) |
| [VST-003](tickets/VST-003.md) | Context and ticket workflow | [VST-003](branches/VST-003.md) |
| [VST-004](tickets/VST-004.md) | Four feature specifications and development plan | [VST-004](branches/VST-004.md) |
| [VST-008](tickets/VST-008.md) | Operation inventory and shared capability contract | [VST-008](branches/VST-008.md) |
| [VST-005](tickets/VST-005.md) | Static host and authenticated workspace service | [VST-005](branches/VST-005.md) |
| [VST-006](tickets/VST-006.md) | Capability registry and extension authoring | [VST-006](branches/VST-006.md) |
| [VST-011](tickets/VST-011.md) | Authenticated workspace MCP transport | [VST-011](branches/VST-011.md) |
| [VST-017](tickets/VST-017.md) | Codespaces persistence and authenticated readiness | [VST-017](branches/VST-017.md) |
| [VST-012](tickets/VST-012.md) | Registered workspace tools and local stdio bridge | [VST-012](branches/VST-012.md) |
| [VST-009](tickets/VST-009.md) | One-URL guidance and verified CLI distribution | [VST-009](branches/VST-009.md) |
| [VST-010](tickets/VST-010.md) | Cross-client parity and compatibility | [VST-010](branches/VST-010.md) |
| [VST-013](tickets/VST-013.md) | MCP transport recovery and compatibility | [VST-013](branches/VST-013.md) |
| [VST-014](tickets/VST-014.md) | Provider catalog, activation and runtime adapters | [VST-014](branches/VST-014.md) |
| [VST-015](tickets/VST-015.md) | Agent icon, chat and guided provider setup | [VST-015](branches/VST-015.md) |
| [VST-016](tickets/VST-016.md) | Legacy UI removal and provider-preserving migration | [VST-016](branches/VST-016.md) |
| [VST-007](tickets/VST-007.md) | Fresh Codespace and extension lifecycle acceptance | [VST-007](branches/VST-007.md) |

Read status from the ticket on the ref you are inspecting. This table deliberately
contains no status column. The first two records are retrospective. The workflow and four draft
specifications reached main on 2026-09-21. The feature queue links planned
implementation work; checking in a specification does not implement it.

Tickets VST-005 through VST-016 are indexed in their
[specification plans](specifications/README.md). The table above links their
registered branches; future tickets without a manifest have no execution branch yet. Read each ticket for
its current phase and next action.
