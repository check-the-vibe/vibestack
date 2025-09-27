# GPT-5 Codex Guide

Use this reference when collaborating with GPT-5 Codex inside VibeStack. It distills the official prompting guidance and adds project-specific integrations so every agent can move quickly without sacrificing quality.

## Core Principles
- **State the outcome first:** Describe the user-facing change or artifact you expect ("Add a Sessions overview page"), then outline constraints (tech debt, latency budgets, approval rules).
- **Anchor Codex in context:** Provide relevant file paths, APIs, and data contracts. Short, curated snippets beat whole files and help Codex stay precise.
- **Structure multi-step work:** Ask Codex to produce a plan when the change touches several files or services; confirm or adjust the plan before granting approval to execute it.
- **Be explicit about format:** Call out whether you need shell commands, code blocks, config diffs, or natural-language explanations. Mention required file names when creating new artifacts.
- **Iterate with feedback:** After each response, summarize what is correct, what needs adjustment, and which follow-up command or edit should happen next.

## Prompt Patterns
| Situation | Recommended Pattern |
| --- | --- |
| Large feature or refactor | `Goal → Constraints → Artifacts → Approval` checklist before any code is generated. |
| Focused edit | Quote the relevant function or snippet, then ask for the minimal change ("Update validation message in `streamlit_app/pages/sessions.py`"). |
| Design discussion | Ask Codex to "reason about" trade-offs or list options, then choose the preferred path before coding. |
| Incident debug | Supply logs plus hypothesis, request a diagnostic plan, and confirm before running disruptive commands. |

## Working with the Codex CLI
- Launch sessions with `vibe create <name> --template codex`. The default template will set `--danger-full-access` unless you override it in the UI or CLI.
- Use the Streamlit Sessions page to toggle Codex CLI parameters (model, sandbox, approval policy, search) and align the working directory before launch. Document custom bundles in `TASKS.md` so they become reusable presets.
- Guardrail tips:
  - `codex plan` yields high-level steps; review before running.
  - `codex diff` surfaces unstaged changes for inspection.
  - `codex run --dry-run` validates shell commands without executing them (when applicable).

## Validation Workflow
1. **Plan review** – Confirm the proposed sequence matches the task list and does not overlook migrations, API contracts, or UI wiring.
2. **Implementation** – Apply edits in small batches; prefer `rg` for searches and keep commits focused.
3. **Automated checks** – Run targeted tests (`pytest`, `npm test`, `python -m mypy`, etc.) and capture outputs in your notes.
4. **Manual verification** – Exercise the Streamlit UI (see `docs/services/streamlit-ui.md`) or API endpoints as needed.
5. **Documentation sync** – Update `AGENTS.md`, service guides, or runbooks whenever behavior changes.
6. **Task closure** – Mark completed work in `TASKS.md` and flag follow-ups under "Follow-ups" if additional effort is required.

## Quick Checklist Before You Finish
- [ ] Re-ran or summarized the relevant tests.
- [ ] Captured key decisions, TODOs, and regressions avoided.
- [ ] Linked affected files and line numbers in the hand-off message.
- [ ] Ensured sensitive credentials or tokens never left the container.

Keep refining these heuristics—add new patterns or anti-patterns you discover to this document so the next agent benefits immediately.
