# Projector Integration for Amplifier TUI

Instructions for adding Projector project awareness to the TUI app.

## What Is Projector

Projector is a cross-session project management and strategy layer (`ramparte/amplifier-bundle-projector`). It stores:

- **Projects** at `~/.amplifier/projector/projects/<name>/project.yaml` - name, description, repos, relationships, status
- **Strategies** at `~/.amplifier/projector/strategies/<name>.yaml` - global working preferences injected into sessions
- **Tasks** at `~/.amplifier/projector/projects/<name>/tasks.yaml` - per-project task tracking
- **Outcomes** at `~/.amplifier/projector/projects/<name>/outcomes.jsonl` - append-only session outcome log

The distro already has a Projector plugin with REST routes at `server/apps/projector/`. The TUI should use those routes when available, with direct file reads as fallback.

## Goal

Add a Projector panel to the TUI that shows projects, their status, active tasks, recent outcomes, and strategies. Sessions should be associable with Projector projects (beyond the existing filesystem-path grouping). The existing `/project` commands should be enriched with Projector data when available.

## Architecture Decisions

- **New files over modifying app.py** - app.py is 7,200+ lines. Minimize touch points there (imports, compose, slash registration). All logic goes in new files.
- **Follow existing patterns** - TodoPanel and AgentTreePanel are the template for the panel widget. ProjectCommandsMixin is the template for commands. JsonStore is the template for persistence.
- **Distro API first, file fallback** - Try the Bridge API routes. If unavailable (standalone TUI without distro), read files directly from `~/.amplifier/projector/`.
- **SharedAppBase for cross-platform** - Put logic in `core/` so the web frontend can reuse it.

## Files to Create (4 new files)

### 1. `amplifier_tui/core/features/projector_client.py`

Data access layer for Projector state. This is NOT an HTTP client - it reads the same files that the Projector tool reads, since the TUI runs in-process.

```python
"""Projector data access for TUI."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ProjectorProject:
    """A Projector project."""
    name: str
    description: str
    status: str  # active, paused, completed, idea
    repos: list[str] = field(default_factory=list)
    relationships: list[dict[str, str]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    task_count: int = 0
    recent_outcomes: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ProjectorStrategy:
    """A Projector strategy."""
    name: str
    description: str
    active: bool
    scope: str  # global or project-specific
    tags: list[str] = field(default_factory=list)


@dataclass
class ProjectorTask:
    """A task within a project."""
    id: str
    title: str
    status: str  # pending, in_progress, completed, blocked
    priority: str = "medium"
    project: str = ""


class ProjectorClient:
    """
    Reads Projector data from ~/.amplifier/projector/.

    This is a read-only client for the TUI to display Projector state.
    Mutations go through the Projector tool (in-session) or distro API.
    """

    def __init__(self, data_path: Path | None = None):
        self._data_path = data_path or Path.home() / ".amplifier" / "projector"

    @property
    def available(self) -> bool:
        """Check if Projector data exists."""
        return self._data_path.exists()

    def list_projects(self) -> list[ProjectorProject]:
        """List all projects with task counts and recent outcomes."""
        projects_dir = self._data_path / "projects"
        if not projects_dir.exists():
            return []

        results = []
        for proj_dir in sorted(projects_dir.iterdir()):
            proj_file = proj_dir / "project.yaml"
            if not proj_file.exists():
                continue
            try:
                data = yaml.safe_load(proj_file.read_text())
                proj = ProjectorProject(
                    name=data.get("name", proj_dir.name),
                    description=data.get("description", ""),
                    status=data.get("status", "active"),
                    repos=data.get("repos", []),
                    relationships=data.get("relationships", []),
                    tags=data.get("tags", []),
                )
                # Count tasks
                tasks_file = proj_dir / "tasks.yaml"
                if tasks_file.exists():
                    tasks = yaml.safe_load(tasks_file.read_text())
                    if isinstance(tasks, list):
                        proj.task_count = len([t for t in tasks if t.get("status") != "completed"])

                # Last 3 outcomes
                outcomes_file = proj_dir / "outcomes.jsonl"
                if outcomes_file.exists():
                    lines = outcomes_file.read_text().strip().splitlines()
                    for line in lines[-3:]:
                        try:
                            proj.recent_outcomes.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass

                results.append(proj)
            except Exception:
                continue

        return results

    def get_project(self, name: str) -> ProjectorProject | None:
        """Get a single project by name."""
        for p in self.list_projects():
            if p.name == name:
                return p
        return None

    def list_strategies(self, active_only: bool = True) -> list[ProjectorStrategy]:
        """List strategies."""
        strat_dir = self._data_path / "strategies"
        if not strat_dir.exists():
            return []

        results = []
        for f in sorted(strat_dir.glob("*.yaml")):
            try:
                data = yaml.safe_load(f.read_text())
                strat = ProjectorStrategy(
                    name=data.get("name", f.stem),
                    description=data.get("description", ""),
                    active=data.get("active", True),
                    scope=data.get("scope", "global"),
                    tags=data.get("tags", []),
                )
                if active_only and not strat.active:
                    continue
                results.append(strat)
            except Exception:
                continue

        return results

    def get_tasks(self, project_name: str) -> list[ProjectorTask]:
        """Get tasks for a project."""
        tasks_file = self._data_path / "projects" / project_name / "tasks.yaml"
        if not tasks_file.exists():
            return []

        try:
            data = yaml.safe_load(tasks_file.read_text())
            if not isinstance(data, list):
                return []
            return [
                ProjectorTask(
                    id=t.get("id", ""),
                    title=t.get("title", ""),
                    status=t.get("status", "pending"),
                    priority=t.get("priority", "medium"),
                    project=project_name,
                )
                for t in data
            ]
        except Exception:
            return []

    def detect_project(self, working_dir: str | Path) -> ProjectorProject | None:
        """
        Detect which Projector project matches a working directory.

        Checks if any project's repos list contains a path that matches
        the working directory (by basename or full path).
        """
        working_dir = Path(working_dir)
        dir_name = working_dir.name

        for proj in self.list_projects():
            for repo in proj.repos:
                repo_name = Path(repo).name if "/" in repo else repo
                if repo_name == dir_name or str(working_dir).endswith(repo):
                    return proj
        return None
```

**Pattern notes:**
- Follows the same structure as `project_aggregator.py` (dataclasses + reader class)
- Read-only - mutations happen through the Projector tool or distro API
- `detect_project()` matches the hook's project detection logic
- No HTTP dependency - reads files directly like the existing session scanner

### 2. `amplifier_tui/widgets/project_panel.py`

Right-docked panel showing Projector projects. Follow the TodoPanel/AgentTreePanel pattern exactly.

```python
"""Projector project panel widget."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


class ProjectItem(Static):
    """A single project in the panel."""

    DEFAULT_CSS = """
    ProjectItem {
        padding: 0 1;
        height: auto;
    }
    ProjectItem:hover {
        background: $surface-lighten-1;
    }
    """

    def __init__(self, name: str, status: str, task_count: int, **kwargs):
        self._project_name = name
        self._status = status
        self._task_count = task_count
        super().__init__(**kwargs)

    def compose(self) -> ComposeResult:
        status_icon = {"active": "*", "paused": "~", "completed": "+", "idea": "?"}
        icon = status_icon.get(self._status, " ")
        tasks = f" [{self._task_count} tasks]" if self._task_count > 0 else ""
        yield Static(f"[{icon}] {self._project_name}{tasks}")


class ProjectPanel(Widget):
    """Right-docked panel showing Projector projects and strategies."""

    DEFAULT_CSS = """
    ProjectPanel {
        dock: right;
        width: 40;
        display: none;
        border-left: solid $surface-lighten-2;
        background: $surface;
    }
    ProjectPanel.visible {
        display: block;
    }
    ProjectPanel .panel-title {
        text-style: bold;
        padding: 0 1;
        color: $text;
        background: $surface-lighten-1;
    }
    ProjectPanel .section-header {
        text-style: bold;
        padding: 1 1 0 1;
        color: $text-muted;
    }
    ProjectPanel .strategy-item {
        padding: 0 1 0 2;
        color: $text-muted;
    }
    """

    visible: reactive[bool] = reactive(False)

    def compose(self) -> ComposeResult:
        yield Static("Projector", classes="panel-title")
        yield VerticalScroll(id="project-panel-content")

    def watch_visible(self, value: bool) -> None:
        if value:
            self.add_class("visible")
        else:
            self.remove_class("visible")

    def update_projects(self, projects: list, strategies: list) -> None:
        """
        Refresh the panel content.

        Args:
            projects: list of ProjectorProject dataclass instances
            strategies: list of ProjectorStrategy dataclass instances
        """
        container = self.query_one("#project-panel-content", VerticalScroll)
        container.remove_children()

        # Projects section
        container.mount(Static("Projects", classes="section-header"))
        if not projects:
            container.mount(Static("  No projects found", classes="strategy-item"))
        for proj in projects:
            container.mount(ProjectItem(
                name=proj.name,
                status=proj.status,
                task_count=proj.task_count,
            ))

        # Strategies section
        container.mount(Static("Strategies", classes="section-header"))
        for strat in strategies:
            tag = "on" if strat.active else "off"
            container.mount(Static(
                f"  [{tag}] {strat.name}",
                classes="strategy-item",
            ))
```

**Pattern notes:**
- Identical structure to `todo_panel.py` (reactive visibility, dock right, `watch_visible`)
- `update_projects()` follows the same pattern as `TodoPanel.update_todos()`
- Uses only `Static` widgets for simplicity - can be enhanced later with click handlers, Tree widget, etc.

### 3. `amplifier_tui/core/commands/projector_cmds.py`

Command mixin for `/projector` slash commands. Follow the pattern in `project_cmds.py`.

```python
"""Projector slash command mixin."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass  # avoid circular imports


class ProjectorCommandsMixin:
    """
    Adds /projector commands to the TUI.

    Slash commands:
        /projector           - Toggle project panel, refresh data
        /projector projects  - List all projects with status
        /projector tasks     - Show tasks for current/named project
        /projector strategies - List active strategies
        /projector status    - Show current project context (detected from cwd)
        /projector outcomes <name> - Show recent session outcomes for a project
    """

    async def _cmd_projector(self, args: str) -> None:
        """Handle /projector commands."""
        parts = args.strip().split(maxsplit=1)
        subcmd = parts[0] if parts else ""
        rest = parts[1] if len(parts) > 1 else ""

        if not subcmd:
            # Toggle panel and refresh
            await self._projector_toggle_panel()
            return

        handlers = {
            "projects": self._projector_list_projects,
            "tasks": self._projector_show_tasks,
            "strategies": self._projector_list_strategies,
            "status": self._projector_show_status,
            "outcomes": self._projector_show_outcomes,
        }

        handler = handlers.get(subcmd)
        if handler:
            await handler(rest)
        else:
            self._append_system_message(
                f"Unknown projector command: {subcmd}\n"
                "Available: projects, tasks, strategies, status, outcomes"
            )

    async def _projector_toggle_panel(self) -> None:
        """Toggle the project panel visibility and refresh its data."""
        if not hasattr(self, "_projector_client"):
            self._init_projector()

        panel = self.query_one("#project-panel", expect_type=None)
        if panel is None:
            self._append_system_message("Project panel not available")
            return

        panel.visible = not panel.visible
        if panel.visible:
            await self._projector_refresh_panel()

    async def _projector_refresh_panel(self) -> None:
        """Refresh the project panel with current data."""
        if not hasattr(self, "_projector_client"):
            self._init_projector()

        client = self._projector_client
        if not client.available:
            self._append_system_message(
                "Projector data not found at ~/.amplifier/projector/\n"
                "Install: amplifier bundle add "
                "git+https://github.com/ramparte/amplifier-bundle-projector@main"
            )
            return

        projects = client.list_projects()
        strategies = client.list_strategies(active_only=True)

        panel = self.query_one("#project-panel", expect_type=None)
        if panel is not None:
            panel.update_projects(projects, strategies)

    async def _projector_list_projects(self, args: str) -> None:
        """List all Projector projects."""
        if not hasattr(self, "_projector_client"):
            self._init_projector()

        projects = self._projector_client.list_projects()
        if not projects:
            self._append_system_message("No Projector projects found.")
            return

        lines = ["**Projector Projects**\n"]
        for p in projects:
            status_icon = {"active": "*", "paused": "~", "completed": "+", "idea": "?"}
            icon = status_icon.get(p.status, " ")
            tasks = f" ({p.task_count} tasks)" if p.task_count else ""
            lines.append(f"  [{icon}] **{p.name}**{tasks} - {p.description[:60]}")

        self._append_system_message("\n".join(lines))

    async def _projector_show_tasks(self, project_name: str) -> None:
        """Show tasks for a project (auto-detects if no name given)."""
        if not hasattr(self, "_projector_client"):
            self._init_projector()

        if not project_name:
            detected = self._projector_detect_current()
            if detected:
                project_name = detected.name
            else:
                self._append_system_message(
                    "No project specified and none detected from cwd. "
                    "Usage: /projector tasks <name>"
                )
                return

        tasks = self._projector_client.get_tasks(project_name)
        if not tasks:
            self._append_system_message(f"No tasks for {project_name}")
            return

        lines = [f"**Tasks: {project_name}**\n"]
        for t in tasks:
            icon = {
                "pending": "[ ]", "in_progress": "[>]",
                "completed": "[x]", "blocked": "[!]",
            }
            lines.append(f"  {icon.get(t.status, '[ ]')} {t.id}: {t.title}")

        self._append_system_message("\n".join(lines))

    async def _projector_list_strategies(self, args: str) -> None:
        """List active strategies."""
        if not hasattr(self, "_projector_client"):
            self._init_projector()

        strategies = self._projector_client.list_strategies(
            active_only="all" not in args
        )
        if not strategies:
            self._append_system_message("No strategies found.")
            return

        lines = ["**Active Strategies**\n"]
        for s in strategies:
            tag = "on" if s.active else "off"
            lines.append(f"  [{tag}] **{s.name}** - {s.description[:60]}")

        self._append_system_message("\n".join(lines))

    async def _projector_show_status(self, args: str) -> None:
        """Show Projector context for current working directory."""
        if not hasattr(self, "_projector_client"):
            self._init_projector()

        detected = self._projector_detect_current()
        if not detected:
            self._append_system_message(
                "No Projector project detected for current directory.\n"
                "Use /projector projects to see all projects."
            )
            return

        lines = [
            f"**Project: {detected.name}**",
            f"Status: {detected.status}",
            f"Repos: {', '.join(detected.repos) if detected.repos else 'none'}",
        ]
        if detected.task_count:
            lines.append(f"Active tasks: {detected.task_count}")
        if detected.recent_outcomes:
            lines.append("\n**Recent outcomes:**")
            for o in detected.recent_outcomes[-3:]:
                summary = o.get("summary", "no summary")[:80]
                lines.append(f"  - {summary}")

        self._append_system_message("\n".join(lines))

    async def _projector_show_outcomes(self, project_name: str) -> None:
        """Show recent session outcomes for a project."""
        if not hasattr(self, "_projector_client"):
            self._init_projector()

        if not project_name:
            detected = self._projector_detect_current()
            project_name = detected.name if detected else ""

        if not project_name:
            self._append_system_message("Usage: /projector outcomes <name>")
            return

        proj = self._projector_client.get_project(project_name)
        if not proj:
            self._append_system_message(f"Project not found: {project_name}")
            return

        if not proj.recent_outcomes:
            self._append_system_message(f"No recorded outcomes for {project_name}")
            return

        lines = [f"**Recent Outcomes: {project_name}**\n"]
        for o in proj.recent_outcomes:
            ts = o.get("timestamp", "?")[:10]
            summary = o.get("summary", "no summary")
            lines.append(f"  [{ts}] {summary}")

        self._append_system_message("\n".join(lines))

    def _projector_detect_current(self):
        """Detect Projector project from current session's working dir."""
        import os
        cwd = os.getcwd()

        # If we have an active session with a working dir, prefer that
        if hasattr(self, "_current_conversation_id"):
            conv_id = self._current_conversation_id
            if hasattr(self, "_session_manager"):
                handle = self._session_manager.get_handle(conv_id)
                if handle and hasattr(handle, "working_dir") and handle.working_dir:
                    cwd = handle.working_dir

        return self._projector_client.detect_project(cwd)

    def _init_projector(self) -> None:
        """Lazily initialize the Projector client."""
        from amplifier_tui.core.features.projector_client import ProjectorClient
        self._projector_client = ProjectorClient()
```

**Pattern notes:**
- Follows `ProjectCommandsMixin` exactly (underscore-prefixed methods, `_append_system_message` for output)
- Lazy init pattern matches how other features initialize
- `_projector_detect_current()` mirrors the hook's project detection

### 4. `amplifier_tui/core/persistence/projector_links.py`

Store manual session-to-project associations (beyond auto-detection).

```python
"""Session-to-Projector-project link store."""

from __future__ import annotations

from amplifier_tui.core.persistence._base import JsonStore


class ProjectorLinkStore(JsonStore):
    """
    Maps session_id -> projector_project_name.

    Used when a user manually associates a session with a Projector project
    (e.g., /projector link <project>), overriding auto-detection.
    """

    def link(self, session_id: str, project_name: str) -> None:
        self._data[session_id] = project_name
        self.save()

    def unlink(self, session_id: str) -> None:
        self._data.pop(session_id, None)
        self.save()

    def get_project(self, session_id: str) -> str | None:
        return self._data.get(session_id)

    def sessions_for_project(self, project_name: str) -> list[str]:
        return [sid for sid, pname in self._data.items() if pname == project_name]
```

Store file: `~/.amplifier/tui-projector-links.json`

## Wiring Into app.py (Minimal Touches)

These are the specific lines to change in `app.py`. Keep changes minimal.

### A. Imports (near line 62-85)

```python
from amplifier_tui.widgets.project_panel import ProjectPanel
from amplifier_tui.core.commands.projector_cmds import ProjectorCommandsMixin
```

### B. Class inheritance (near line 148)

Add `ProjectorCommandsMixin` to the class inheritance list:

```python
class AmplifierTuiApp(
    MonitorCommandsMixin,
    TerminalCommandsMixin,
    ShellCommandsMixin,
    DashboardCommandsMixin,
    ProjectCommandsMixin,
    ProjectorCommandsMixin,    # <-- add here
    ...
)
```

### C. Store initialization (near line 470-494)

```python
self._projector_link_store = ProjectorLinkStore(_amp_home / "tui-projector-links.json")
```

### D. compose() method (near line 569-614)

Add alongside TodoPanel and AgentTreePanel:

```python
yield ProjectPanel(id="project-panel")
```

### E. Slash command registration (near line 3641-3664)

In the slash command routing:

```python
"/projector": self._cmd_projector,
```

### F. Keybinding (optional)

Add to BINDINGS:

```python
Binding("ctrl+p", "toggle_project_panel", "Projects", show=False),
```

With action method:

```python
def action_toggle_project_panel(self) -> None:
    panel = self.query_one("#project-panel", ProjectPanel)
    panel.visible = not panel.visible
    if panel.visible:
        self.run_worker(self._projector_refresh_panel())
```

## styles.tcss Additions

Add near the other panel styles:

```css
/* Projector Panel */
#project-panel {
    dock: right;
    width: 40;
    display: none;
    border-left: solid $surface-lighten-2;
    background: $surface;
}

#project-panel.visible {
    display: block;
}
```

Note: The widget's DEFAULT_CSS handles most styling. The tcss additions are for app-level overrides.

## Future Enhancements (Not in this pass)

1. **Breadcrumb integration** - Show active Projector project in `#breadcrumb-bar` when detected
2. **Sidebar grouping** - Add "group by Projector project" as a sidebar sort mode in `_populate_session_list()`
3. **Project detail screen** - Full-screen modal showing project description, all tasks, outcome history, related projects
4. **Click handlers** - Clicking a project in the panel filters the sidebar to that project's sessions
5. **Strategy toggle** - Click to enable/disable strategies from the panel
6. **Auto-refresh** - Periodically refresh panel data (like auto-tagger's 30s timer)
7. **Web frontend** - Since commands are in `core/commands/`, the web app can reuse `ProjectorCommandsMixin` with its own rendering

## Testing Notes

- `ProjectorClient` reads files only - test by creating fixture data at a temp path
- The panel widget can be tested with Textual's `async with app.run_test()` pattern
- Integration test: create session in a directory matching a Projector project's repo, verify `detect_project()` returns it

## Projector Data Reference

For context, here's what the data looks like on disk:

**Project** (`~/.amplifier/projector/projects/amplifier-tui/project.yaml`):
```yaml
name: amplifier-tui
description: Terminal user interface for Amplifier sessions
status: active
repos: [ramparte/amplifier-tui]
relationships:
  - type: part_of
    target: amplifier-distro
  - type: related_to
    target: amplifier-web
tags: [ui, frontend, textual]
```

**Strategy** (`~/.amplifier/projector/strategies/subagent-first.yaml`):
```yaml
name: subagent-first
description: Preserve main session context by delegating exploration to sub-agents.
active: true
scope: global
enforcement: soft
injection: |
  When exploring or understanding code involving more than 2 files, always
  delegate to explorer or code-intel sub-agents...
tags: [context-management, delegation, session-health]
```

**Tasks** (`~/.amplifier/projector/projects/amplifier-tui/tasks.yaml`):
```yaml
- id: tui-001
  title: Add Projector panel
  status: pending
  priority: high
- id: tui-002
  title: Breadcrumb integration
  status: pending
  priority: medium
```

**Outcomes** (`~/.amplifier/projector/projects/amplifier-tui/outcomes.jsonl`):
```json
{"timestamp": "2026-02-12T14:00:00Z", "session_id": "abc123", "summary": "Added project tagging feature", "capabilities": ["project-management", "ui"]}
```
