"""Module-level constants for Amplifier TUI."""

from __future__ import annotations

from .platform_info import DANGEROUS_PATTERNS as _DANGEROUS_PATTERNS  # noqa: F401 - re-exported
from .platform_info import amplifier_home

# Tool name -> human-friendly status label (without trailing "...")
TOOL_LABELS: dict[str, str] = {
    "read_file": "Reading file",
    "write_file": "Writing file",
    "edit_file": "Editing file",
    "grep": "Searching",
    "glob": "Finding files",
    "bash": "Running command",
    "web_search": "Searching web",
    "web_fetch": "Fetching page",
    "delegate": "Delegating to agent",
    "task": "Delegating to agent",
    "LSP": "Analyzing code",
    "python_check": "Checking code",
    "todo": "Planning",
    "recipes": "Running recipe",
    "load_skill": "Loading skill",
}

_MAX_LABEL_LEN = 38  # Keep status labels under ~40 chars total

# /run shell execution settings
# _DANGEROUS_PATTERNS is imported from .platform (platform-aware)
_MAX_RUN_OUTPUT_LINES = 100
_RUN_TIMEOUT = 30

# Auto-save directory and defaults
AUTOSAVE_DIR = amplifier_home() / "tui-autosave"
MAX_AUTOSAVES_PER_TAB = 5

# Canonical list of slash commands – used by both _handle_slash_command and
# ChatInput tab-completion.  Keep in sync with the handlers dict below.
SLASH_COMMANDS: tuple[str, ...] = (
    "/agents",
    "/agents tree",
    "/alias",
    "/attach",
    "/auto",
    "/auto edit",
    "/auto full",
    "/auto suggest",
    "/autosave",
    "/bm",
    "/bookmark",
    "/bookmarks",
    "/branch",
    "/branch compare",
    "/branch delete",
    "/branch list",
    "/branch merge",
    "/branch switch",
    "/branches",
    "/cat",
    "/clear",
    "/clip",
    "/clipboard",
    "/colors",
    "/commands",
    "/commit",
    "/compact",
    "/compare",
    "/compare clear",
    "/compare history",
    "/compare off",
    "/compare pick",
    "/compare show",
    "/compare status",
    "/context",
    "/context detail",
    "/context history",
    "/context top",
    "/contextwindow",
    "/copy",
    "/dashboard",
    "/dashboard clear",
    "/dashboard export",
    "/dashboard heatmap",
    "/dashboard refresh",
    "/dashboard summary",
    "/delete",
    "/diff",
    "/diff last",
    "/draft",
    "/drafts",
    "/edit",
    "/editor",
    "/env",
    "/environment",
    "/exit",
    "/export",
    "/find",
    "/focus",
    "/fold",
    "/fork",
    "/git",
    "/gitstatus",
    "/grep",
    "/gs",
    "/help",
    "/history",
    "/include",
    "/include git",
    "/include preview",
    "/include recent",
    "/include tree",
    "/info",
    "/keys",
    "/ml",
    "/mode",
    "/model",
    "/modes",
    "/monitor",
    "/monitor big",
    "/monitor close",
    "/monitor small",
    "/multiline",
    "/name",
    "/new",
    "/note",
    "/notes",
    "/notify",
    "/palette",
    "/pin",
    "/pin-session",
    "/pins",
    "/plugins",
    "/plugins help",
    "/plugins reload",
    "/preferences",
    "/prefs",
    "/progress",
    "/quit",
    "/recipe",
    "/recipe clear",
    "/recipe history",
    "/recipe run",
    "/recipe status",
    "/redo",
    "/ref",
    "/refs",
    "/rename",
    "/replay",
    "/replay clear",
    "/replay pause",
    "/replay resume",
    "/replay skip",
    "/replay speed",
    "/replay status",
    "/replay stop",
    "/replay timeline",
    "/retry",
    "/run",
    "/scroll",
    "/search",
    "/sessions",
    "/shell",
    "/showtokens",
    "/skills",
    "/skills load",
    "/snip",
    "/snippet",
    "/snippets",
    "/sort",
    "/sound",
    "/split",
    "/stats",
    "/stream",
    "/suggest",
    "/system",
    "/tab",
    "/tabs",
    "/tag",
    "/tags",
    "/template",
    "/templates",
    "/terminal",
    "/theme",
    "/timestamps",
    "/title",
    "/todo",
    "/tokens",
    "/tools",
    "/tools clear",
    "/tools live",
    "/tools log",
    "/tools stats",
    "/ts",
    "/undo",
    "/unfold",
    "/unpin",
    "/vim",
    "/watch",
    "/workspace",
    "/wrap",
)

# -- Amplifier mode definitions ------------------------------------------------
MODES: dict[str, dict[str, str]] = {
    "planning": {
        "description": "Planning mode \u2014 analysis and decomposition, no implementation",
        "indicator": "[planning]",
        "accent": "#536dfe",
    },
    "research": {
        "description": "Research mode \u2014 deep investigation and exploration",
        "indicator": "[research]",
        "accent": "#00bfa5",
    },
    "review": {
        "description": "Code review mode \u2014 systematic code assessment",
        "indicator": "[review]",
        "accent": "#ff9100",
    },
    "debug": {
        "description": "Debug mode \u2014 systematic issue investigation",
        "indicator": "[debug]",
        "accent": "#ff5252",
    },
}

# -- Prompt templates for smart suggestions ------------------------------------
PROMPT_TEMPLATES: tuple[str, ...] = (
    "Explain this code: ",
    "Fix the bug in ",
    "Refactor this to be more ",
    "Write tests for ",
    "Review this code for ",
    "What does this error mean: ",
    "Summarize the conversation so far",
    "Create a plan for ",
    "Debug why ",
    "How do I ",
    "What is the best way to ",
    "Compare the approaches for ",
    "Optimize the performance of ",
    "Add error handling to ",
    "Document the ",
)

# -- System prompt presets -----------------------------------------------------
SYSTEM_PRESETS: dict[str, str] = {
    "coder": (
        "You are an expert programmer. Write clean, efficient, well-documented"
        " code. Prefer simplicity over cleverness."
    ),
    "reviewer": (
        "You are a thorough code reviewer. Focus on bugs, security issues,"
        " performance problems, and best practices. Be specific and actionable."
    ),
    "teacher": (
        "You are a patient, knowledgeable teacher. Explain concepts clearly"
        " with examples. Build understanding step by step."
    ),
    "concise": (
        "Be extremely concise. Use bullet points and short sentences. No filler"
        " words or unnecessary elaboration."
    ),
    "creative": (
        "Think creatively and explore unconventional approaches. Challenge"
        " assumptions. Suggest novel solutions."
    ),
    "debug": (
        "You are a debugging expert. Think systematically about potential"
        " causes. Ask clarifying questions. Trace logic step by step."
    ),
    "architect": (
        "You are a software architect. Focus on system design, scalability,"
        " maintainability, and trade-offs between approaches."
    ),
    "writer": (
        "You are a skilled technical writer. Focus on clarity, structure, and"
        " accuracy. Write for the intended audience."
    ),
}

# -- Model aliases and catalog ------------------------------------------------

MODEL_ALIASES: dict[str, str] = {
    # Claude models
    "sonnet": "claude-sonnet-4-20250514",
    "haiku": "claude-haiku-35-20241022",
    "opus": "claude-3-opus-20240229",
    # GPT models
    "gpt4": "gpt-4o",
    "gpt4o": "gpt-4o",
    "gpt4-mini": "gpt-4o-mini",
    "o1": "o1",
    "o3": "o3-mini",
    # Shorthand
    "fast": "claude-haiku-35-20241022",
    "smart": "claude-sonnet-4-20250514",
    "best": "claude-3-opus-20240229",
}

AVAILABLE_MODELS: tuple[tuple[str, str, str], ...] = (
    # (model_id, provider, description)
    ("claude-sonnet-4-20250514", "Anthropic", "Claude Sonnet 4 (balanced)"),
    ("claude-haiku-35-20241022", "Anthropic", "Claude Haiku 3.5 (fast)"),
    ("claude-3-opus-20240229", "Anthropic", "Claude Opus (powerful)"),
    ("gpt-4o", "OpenAI", "GPT-4o (balanced)"),
    ("gpt-4o-mini", "OpenAI", "GPT-4o Mini (fast)"),
    ("o1", "OpenAI", "O1 (reasoning)"),
    ("o3-mini", "OpenAI", "O3 Mini (reasoning)"),
)

# -- /include constants -------------------------------------------------------

MAX_INCLUDE_LINES = 500
MAX_INCLUDE_SIZE = 100_000  # 100 KB

EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "jsx",
    ".tsx": "tsx",
    ".rs": "rust",
    ".go": "go",
    ".rb": "ruby",
    ".java": "java",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".swift": "swift",
    ".kt": "kotlin",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "zsh",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".xml": "xml",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".sql": "sql",
    ".md": "markdown",
    ".txt": "",
    ".cfg": "ini",
    ".ini": "ini",
    ".env": "bash",
    ".dockerfile": "dockerfile",
    ".tf": "hcl",
    ".lua": "lua",
    ".r": "r",
    ".R": "r",
}

MAX_TABS = 10  # Maximum number of concurrent tabs

MAX_ATTACHMENT_SIZE = 50_000  # 50 KB warning threshold (total)

# Known context window sizes (tokens) for popular models.
# Used as fallback when the provider doesn't report context_window.
MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    "claude-3-5-sonnet": 200_000,
    "claude-3-sonnet": 200_000,
    "claude-3-haiku": 200_000,
    "claude-3-opus": 200_000,
    "claude-sonnet": 200_000,
    "claude-haiku": 200_000,
    "claude-opus": 200_000,
    "gpt-4o-mini": 128_000,
    "gpt-4o": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4": 8_192,
    "gpt-3.5-turbo": 16_385,
    "gpt-3.5": 16_385,
    "o1-mini": 128_000,
    "o1": 200_000,
    "o3-mini": 200_000,
    "o3": 200_000,
    "o4-mini": 200_000,
    "gemini": 1_000_000,
}
DEFAULT_CONTEXT_WINDOW = 200_000
