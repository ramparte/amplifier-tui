# Feature Ideas

Living document of feature ideas for amplifier-tui, inspired by what's happening in the wild with Claude Code, agent tooling, and the broader agentic coding ecosystem. Updated as new signals emerge.

Last updated: 2026-02-11

---

## Token Budget Tracker

**Signal:** Claude Code Pro's 5-hour token window is "catastrophically small" (Jesse). Engineers burning through $1000s/month in tokens. Everyone frustrated by invisible limits.

**Idea:** A persistent status bar widget and `/budget` command that tracks token burn rate across the session. Show: tokens used so far, estimated tokens remaining (based on provider plan), burn rate per turn, projected time until limit. Color-coded like the existing context pressure indicator (green/yellow/orange/red). Optional alert when approaching limit.

**Why achievable:** The TUI already has a context profiler (`core/features/context_profiler.py`) and token stats (`/stats`, `/tokens`). This extends that with rate-of-change tracking and projection. Fits naturally as a new feature module in `core/features/` plus a status bar enhancement.

**Effort:** Low-medium. New feature module + status bar widget update.

---

## Agent Token Attribution

**Signal:** Jesse suspects Claude Code's "explore" agents are burning tokens aggressively. Nobody can see which sub-agents are consuming what.

**Idea:** Extend the existing Agent Tree Panel to show per-agent token consumption. Each node in the tree shows tokens used. Clicking/expanding shows the agent's tool calls and their individual costs. Add a `/agents cost` subcommand that shows a ranked breakdown. Persist across sessions for trend analysis.

**Why achievable:** Agent Tree Panel (`widgets/agent_tree_panel.py`) and agent tracker (`core/features/agent_tracker.py`) already exist. Token data is available in streaming callbacks. This is adding a data column to an existing visualization.

**Effort:** Low-medium. Extend existing agent tracker + tree widget.

---

## Reasoning Trail / Checkpoint Viewer

**Signal:** Entire.io's Checkpoints tool captures agent reasoning, intent, and outcomes alongside code changes. Dohmke: "You can trace at any point in time why decisions were made." The TUI could do this natively.

**Idea:** A `/trail` command that shows the reasoning chain for the current session: what the agent decided, why, what tools it called, what it learned. Displayed as a collapsible timeline in a side panel. Each "checkpoint" is a decision point (tool call, branch taken, agent spawned). Optionally persist as a `.trail.json` alongside session files so future sessions can reference past reasoning.

**Why achievable:** The TUI already captures tool calls in the tool log (`core/features/tool_log.py`) and agent delegations in the agent tracker. This reframes that data as a narrative timeline rather than a flat log. New panel widget + feature module.

**Effort:** Medium. New feature module, new widget, persistence store.

---

## Background Agent Monitor

**Signal:** Claude Code making background/explore agents more prominent. jonchin worried this kills sandbox companies. Jesse noted the UX for viewing agent runs is "definitely getting better" in Claude Code.

**Idea:** Enhance the Agent Tree Panel to distinguish foreground vs. background agents. Show a persistent "background agents running" indicator in the status bar (like a process count). Let users `/attach` to a background agent to watch its output in a split view, or `/detach` to let it run silently. Add `/agents bg` to list only background tasks.

**Why achievable:** The agent tree and split view (`/split`) already exist. This is connecting them and adding foreground/background state tracking.

**Effort:** Medium. Status bar indicator + agent state classification + split view integration.

---

## Session Memory Viewer

**Signal:** Matt Galligan shared Claude's new subagent memory features. Jesse worried about memories in project directory being ephemeral. Yilio: "Memory is genuinely hard."

**Idea:** A `/memory` command and side panel that shows what the agent "remembers" about the current project/session. Display memories from: Amplifier's dev-memory store, Claude's episodic memories (if accessible), and session-local context. Let users view, search, pin, and delete memories. Show when a memory was created and what triggered it.

**Why achievable:** The TUI already has 14 persistence stores and the panel pattern is well-established. The dev-memory system stores data in `~/amplifier-dev-memory/memory-store.yaml`. This is a viewer/editor for that data.

**Effort:** Low-medium. New command + panel widget + read from existing memory stores.

---

## Mode Enforcement Indicator

**Signal:** Noah reported Claude ignoring Superpowers/plan mode 25-30% of the time. Jesse put effort into "don't use plan mode" enforcement. Nat identified episodic memory as the culprit.

**Idea:** A visible mode indicator in the status bar showing the current active mode (planning/research/review/debug/custom). When the agent's behavior appears to deviate from the mode (e.g., writing files in plan mode), flash a warning and offer to inject a corrective prompt. Log mode violations for debugging. The `/mode` command already exists -- this adds observability to it.

**Why achievable:** Modes are already implemented. This adds passive monitoring of tool calls against mode expectations (e.g., plan mode + write_file = violation). Simple rule engine in a feature module.

**Effort:** Low. New feature module that monitors tool calls against active mode rules.

---

## Diff Review Workflow

**Signal:** Dohmke: "A pull request shows me changes to files I never wrote in the first place." The review bottleneck is the central problem. The TUI's existing diff view is partial.

**Idea:** A full `/review` workflow: after the agent makes changes, automatically collect all modified files, show a unified diff view with syntax highlighting, let the user approve/reject/edit individual hunks, and optionally generate a commit message. Integrate with the existing `/git` and `/diff` commands. Add a "changes pending review" badge in the status bar after agent edits.

**Why achievable:** `/git diff`, `/diff`, and `/commit` already exist as separate commands. The diff viewer (`core/features/diff_view.py`) exists. This connects them into a coherent review flow with a badge trigger on file writes.

**Effort:** Medium. Workflow orchestration connecting existing pieces + hunk-level approval UI.

---

## Skills Manager

**Signal:** Jason Huggins suggested toggling different skill sets via symlinks. Navan promised golden dotfiles for agent configuration. Skills are becoming a key configuration surface.

**Idea:** A `/skills` command that lists available skills, shows which are active, and lets users enable/disable/preview skills without leaving the TUI. Show skill metadata (name, description, version) in a browsable list. Support skill sets (named groups of skills you can switch between). Persist active skill sets per project.

**Why achievable:** The skills system uses file-based discovery (`.amplifier/skills/`). This is a file-system browser + symlink manager wrapped in a slash command and optional panel. Follows the same pattern as `/plugins`.

**Effort:** Low-medium. New command mixin + persistence store for skill sets.

---

## Self-Extension Log

**Signal:** Brian Krabach's wife using Amplifier as an end-user: when it can't do something, she has it build more tools for itself. Jesse: "I want that loop to be totally automatic."

**Idea:** When the agent creates new tools, scripts, or configuration files during a session, log these as "self-extensions" in a dedicated panel. Show what was created, why, and where it lives. Let the user promote a self-extension to a permanent tool (move to `.amplifier/` or a skills directory) or discard it. Track which self-extensions get reused across sessions.

**Why achievable:** The tool log already tracks tool calls. This adds a filter for "creative" tool calls (write_file to tool directories, new script creation) and a promotion workflow. New feature module + persistence store.

**Effort:** Medium. Heuristics for detecting self-extension + promotion workflow + persistence.

---

## Cost Dashboard

**Signal:** Dohmke: "In 2026, any leader needs to think about headcount as tokens." Engineers spending $1000s/month. lhl running millions of tokens through multiple providers.

**Idea:** Extend the existing `/dashboard` with a cost-focused view. Show: cost per session, cost per day/week/month, cost by model, cost by agent (using the token attribution above). Support multiple provider pricing models. Show trends over time. Export as CSV for expense reports.

**Why achievable:** Dashboard stats (`core/features/dashboard_stats.py`, 521 lines) already exists. This adds a cost dimension with configurable per-model pricing. The persistence layer for session data already captures token counts.

**Effort:** Medium. Extend dashboard + add pricing configuration + historical aggregation.

---

## Model Hot-Swap

**Signal:** lhl switching between Opus 4.6 and GPT-5.3 Codex, running through Vertex/Bedrock to avoid throttling. People routinely switching models mid-workflow.

**Idea:** A `/model` command (or keybinding) that lets you switch the active model mid-session without starting a new session. Show available models with their current status (rate-limited? available tokens?). Support quick toggles like `/model fast` (cheapest available) vs `/model best` (most capable). Integrate with the existing `/compare` A/B testing feature.

**Why achievable:** The TUI already has model comparison (`core/features/compare_manager.py`). Provider switching is an Amplifier core capability. This surfaces it as a first-class UX element.

**Effort:** Medium. Depends on Amplifier's provider-switching API surface.

---

## Definition of Done Checklist

**Signal:** Jesse on his "4th iteration of no, go find all the problems." The Definition of Done meme in #ai-maximalists. Agents often declare victory prematurely.

**Idea:** A `/done` command that defines completion criteria for the current task. When the agent says it's finished, automatically check the criteria: tests pass? lint clean? no TODOs left? diff reviewed? The checklist appears in a panel (like TodoPanel) and items auto-check as conditions are met. Block the "task complete" celebration until all items green.

**Why achievable:** The TodoPanel pattern is established. This is a specialized variant that monitors external conditions (test results, lint output, git status) instead of just agent-declared state. New feature module + widget.

**Effort:** Medium. Condition monitoring + panel widget + integration with `/git` and test runners.

---

## Session Handoff / Resume Context

**Signal:** Jesse's dorodango concept -- iterative refinement across sessions. The review bottleneck means work spans multiple sessions. Context loss between sessions is painful.

**Idea:** When ending a session, automatically generate a handoff summary: what was accomplished, what's pending, key decisions made, files changed. Store as `SESSION-HANDOFF.md` alongside session files. When resuming or starting a new session in the same project, offer to inject the handoff as context. A `/handoff` command lets you view/edit before closing.

**Why achievable:** Session scanning (`core/features/session_scanner.py`) and export (`/export`) already exist. This combines them into an end-of-session workflow. The handoff file is just a persistence artifact.

**Effort:** Low-medium. Summarization prompt + persistence + resume-time injection.

---

## How to use this document

Pick ideas that excite you. Each one is scoped to be independently implementable. The architectural patterns are consistent:

- **New slash command**: Add to `core/commands/`, register in `core/constants.py`
- **New panel widget**: Follow `widgets/todo_panel.py` pattern
- **New feature module**: Add to `core/features/`, wire in `SharedAppBase`
- **New persistence store**: Extend `core/persistence/` with `JsonStore` subclass

Ideas marked "low effort" can likely be done in a single session. "Medium" might take 2-3 sessions. Nothing here requires architectural changes -- they all fit the existing mixin/panel/feature patterns.
