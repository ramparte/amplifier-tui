# Context Transfer - Completed 2026-02-20

## Status: ALL ITEMS COMPLETE

### 1. CWD Fix (amplifier-tui) - COMMITTED + PUSHED
- **Commit**: `d811d6f` on `feat/web-native-frontend`
- **Fix**: `app.py` now reads `self._prefs.environment.workspace` for session working directory and breadcrumb display, falling back to `os.getcwd()`

### 2. Bundle Resolution Precedence Fix (amplifier-distro) - PR OPEN
- **PR**: https://github.com/ramparte/amplifier-distro/pull/37
- **Branch**: `fix/bundle-resolution-precedence` (rebased onto main, 3 commits)
- **Commits**: `a0deee6`, `b19f07a`, `18f9443`
- **Fix**: Reordered `_resolve_distro_bundle()` so `bundle.active` checked BEFORE convention path
- **Schema change**: `BundleConfig.active` default changed from `"my-amplifier"` to `None`
- **Tests**: 42 passed, 1 pre-existing failure (missing amplifier_core dep, unrelated)

### 3. Provider Injection Fix (amplifier-distro) - IN SAME PR
- **Fix**: `_inject_providers()` reads from `kepler.default_provider` + `kepler.default_model`
- Also includes: server resilience fix for missing optional dependencies

### 4. Desktop Frontend (amplifier-tui) - COMMITTED + PUSHED
- **Commit**: `383b02f` on `feat/web-native-frontend`
- 3,529 lines: 18 Python files (desktop_app.py, 7 widgets, 4 commands, signals, theme)
- `docs/DESKTOP_APP_PLAN.md` (1,072 lines)
- `pyproject.toml` updated with `[desktop]` extra and `amplifier-desktop` entry point

## Architecture Understanding (for future sessions)

### The Three Config Files
| File | Purpose |
|------|---------|
| `~/.amplifier/settings.yaml` | User's bundle/provider prefs (CLI layer) |
| `~/.amplifier/distro.yaml` | Distro config (workspace, identity, kepler, bundle.active) |
| `~/.amplifier/bundles/distro.yaml` | Generated minimal bundle file (foundation + anthropic-sonnet) |

### Bundle Resolution Chain (FIXED)
1. Explicit `BridgeConfig.bundle_name` (surfaces can override)
2. `bundle.active` from `distro.yaml` config (user's choice)
3. Convention file `~/.amplifier/bundles/distro.yaml` (generated default)
4. RuntimeError

### Provider Injection Chain (FIXED)
- When bundle has no providers: reads `kepler.default_provider` + `kepler.default_model`
- User's distro.yaml now configured: `anthropic` + `claude-opus-4-6`
