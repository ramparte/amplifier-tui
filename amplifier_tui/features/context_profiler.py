"""Context window profiler — visual breakdown of context usage.

Pure-function module that analyzes session messages to produce a categorized
breakdown of context window consumption, with stacked bar visualization,
per-message detail, sparkline history, and top-consumer identification.

The message tuples expected are ``(role, content, widget_or_none)`` matching
the ``_search_messages`` format used throughout the TUI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Type alias for the message tuples used throughout the TUI.
# Each entry is (role, content, widget_or_none).
MessageTuple = tuple[str, str, Any]

# Sparkline block characters, lowest to highest
_SPARK_CHARS = "▁▂▃▄▅▆▇█"


def estimate_tokens(text: str) -> int:
    """Estimate token count from text using ~4 chars per token heuristic.

    This is intentionally simple — no tiktoken dependency required.
    Returns at least 1 for any non-empty string.
    """
    if not text:
        return 0
    return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# Message type classification
# ---------------------------------------------------------------------------

# Roles that indicate tool-related content
_TOOL_ROLES = frozenset({"tool", "tool_result", "tool_use"})

# Roles that are system-injected (not conversation)
_SYSTEM_ROLES = frozenset({"system"})

# Roles considered part of the user ↔ assistant conversation
_CONVERSATION_ROLES = frozenset({"user", "assistant"})

# Roles that are metadata / non-context (notes, thinking displayed locally)
_META_ROLES = frozenset({"note", "thinking"})


def _classify_role(role: str) -> str:
    """Classify a message role into a profiler category.

    Returns one of: "system", "conversation", "tool", "injected", "meta".
    """
    r = role.lower().strip()
    if r in _SYSTEM_ROLES:
        return "system"
    if r in _CONVERSATION_ROLES:
        return "conversation"
    if r in _TOOL_ROLES:
        return "tool"
    if r in _META_ROLES:
        return "meta"
    # Anything else (injected context, unknown roles) → injected
    return "injected"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ContextBreakdown:
    """Breakdown of context window usage by category."""

    system_tokens: int = 0
    conversation_tokens: int = 0
    tool_result_tokens: int = 0
    injected_context_tokens: int = 0
    total_capacity: int = 200_000  # override from model info

    @property
    def total_used(self) -> int:
        """Total tokens consumed across all categories."""
        return (
            self.system_tokens
            + self.conversation_tokens
            + self.tool_result_tokens
            + self.injected_context_tokens
        )

    @property
    def available(self) -> int:
        """Tokens remaining before hitting the context window limit."""
        return max(0, self.total_capacity - self.total_used)

    @property
    def usage_percent(self) -> float:
        """Percentage of context window used (0.0–100.0)."""
        if self.total_capacity <= 0:
            return 0.0
        return min(100.0, self.total_used / self.total_capacity * 100)

    @property
    def warning_level(self) -> str:
        """Return severity level based on usage percentage.

        Levels: "normal" (<75%), "warning" (75–85%), "danger" (85–95%),
        "critical" (≥95%).
        """
        pct = self.usage_percent
        if pct >= 95:
            return "critical"
        if pct >= 85:
            return "danger"
        if pct >= 75:
            return "warning"
        return "normal"


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


@dataclass
class MessageInfo:
    """Token info about a single message, used for detail/top-consumer views."""

    index: int
    role: str
    category: str  # "system", "conversation", "tool", "injected"
    tokens: int
    preview: str  # first ~80 chars


def analyze_messages(
    messages: list[MessageTuple],
    total_capacity: int = 200_000,
) -> ContextBreakdown:
    """Analyze a list of messages to produce a context breakdown.

    Parameters
    ----------
    messages
        List of ``(role, content, widget_or_none)`` tuples.
    total_capacity
        Context window size in tokens.

    Categorization by role:
    - system → system_tokens
    - user, assistant → conversation_tokens
    - tool, tool_result, tool_use → tool_result_tokens
    - everything else (except meta) → injected_context_tokens
    """
    breakdown = ContextBreakdown(total_capacity=total_capacity)

    for role, content, _widget in messages:
        cat = _classify_role(role)
        tok = estimate_tokens(content or "")

        if cat == "system":
            breakdown.system_tokens += tok
        elif cat == "conversation":
            breakdown.conversation_tokens += tok
        elif cat == "tool":
            breakdown.tool_result_tokens += tok
        elif cat == "injected":
            breakdown.injected_context_tokens += tok
        # "meta" messages (notes, thinking) don't consume API context

    return breakdown


def analyze_messages_detail(
    messages: list[MessageTuple],
) -> list[MessageInfo]:
    """Return per-message token info for the detail view."""
    result: list[MessageInfo] = []
    for i, (role, content, _widget) in enumerate(messages):
        cat = _classify_role(role)
        if cat == "meta":
            continue
        text = content or ""
        tok = estimate_tokens(text)
        # Build a preview: first ~80 chars, single-line
        preview = text.replace("\n", " ").strip()
        if len(preview) > 80:
            preview = preview[:77] + "..."
        result.append(
            MessageInfo(index=i, role=role, category=cat, tokens=tok, preview=preview)
        )
    return result


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _fmt_tokens(count: int) -> str:
    """Format token count compactly: 1234 → '1.2k', 200000 → '200k'."""
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 10_000:
        val = count / 1_000
        return f"{val:.0f}k" if val >= 100 else f"{val:.1f}k"
    if count >= 1_000:
        return f"{count / 1_000:.1f}k"
    return str(count)


# Category display config: (label, bar_char, color)
_CATEGORIES = [
    ("System prompt", "system_tokens", "S", "cyan"),
    ("Conversation", "conversation_tokens", "C", "blue"),
    ("Tool results", "tool_result_tokens", "T", "magenta"),
    ("Injected context", "injected_context_tokens", "I", "yellow"),
]

_WARNING_COLORS = {
    "normal": "green",
    "warning": "yellow",
    "danger": "#ff8800",
    "critical": "red",
}

_WARNING_ICONS = {
    "normal": "",
    "warning": "⚠",
    "danger": "⚠",
    "critical": "🔴",
}


def format_profiler_bar(breakdown: ContextBreakdown, width: int = 50) -> str:
    """Return a stacked bar visualization with per-category breakdown.

    Output looks like::

        Context: [SSSSCCCCCCCCTTTTTIIII------] 78% (156k / 200k)
          System prompt:    SSSS              12%  (24k)
          Conversation:     CCCCCCCCCCCC      38%  (76k)
          Tool results:     TTTTT             15%  (30k)
          Injected context: IIII              10%  (20k)
          Available:        ------            25%  (50k)
    """
    cap = breakdown.total_capacity
    used = breakdown.total_used
    pct = breakdown.usage_percent
    level = breakdown.warning_level
    # Build the stacked bar
    bar_parts: list[tuple[int, str, str]] = []  # (width, char, color)
    for _label, attr, char, color in _CATEGORIES:
        tokens = getattr(breakdown, attr, 0)
        if cap > 0 and tokens > 0:
            seg_width = max(1, int(tokens / cap * width))
            bar_parts.append((seg_width, char, color))

    # Calculate available segment
    used_width = sum(w for w, _, _ in bar_parts)
    avail_width = max(0, width - used_width)

    # Assemble bar string
    bar_str = ""
    for seg_w, char, _color in bar_parts:
        bar_str += char * seg_w
    bar_str += "-" * avail_width

    # Truncate or pad to exact width
    bar_str = bar_str[:width].ljust(width, "-")

    # Header line
    lines: list[str] = []
    icon = _WARNING_ICONS.get(level, "")
    icon_str = f" {icon}" if icon else ""
    lines.append(
        f"Context: [{bar_str}] {pct:.0f}%"
        f" ({_fmt_tokens(used)} / {_fmt_tokens(cap)}){icon_str}"
    )

    # Per-category breakdown
    for label, attr, char, color in _CATEGORIES:
        tokens = getattr(breakdown, attr, 0)
        cat_pct = (tokens / cap * 100) if cap > 0 else 0.0
        # Build a mini-bar proportional to category's share
        mini_w = max(0, int(cat_pct / 100 * 20))
        mini_bar = char * mini_w
        lines.append(
            f"  {label + ':':<20s} {mini_bar:<20s} {cat_pct:5.1f}%  ({_fmt_tokens(tokens)})"
        )

    # Available line
    avail_pct = (breakdown.available / cap * 100) if cap > 0 else 0.0
    avail_bar = "-" * max(0, int(avail_pct / 100 * 20))
    lines.append(
        f"  {'Available:':<20s} {avail_bar:<20s} {avail_pct:5.1f}%  ({_fmt_tokens(breakdown.available)})"
    )

    # Warning message
    if level == "critical":
        lines.append("")
        lines.append("  🔴 Context nearly full! Start a new session with /new.")
    elif level == "danger":
        lines.append("")
        lines.append("  ⚠ Context is getting full. Consider /compact or /new.")
    elif level == "warning":
        lines.append("")
        lines.append("  ⚠ Context usage is elevated. Monitor with /context.")

    return "\n".join(lines)


def format_profiler_detail(
    messages: list[tuple[str, str, object]],
    breakdown: ContextBreakdown,
) -> str:
    """Return a detailed per-message breakdown.

    Shows each message with its estimated token count, grouped by category,
    and highlights the largest items.
    """
    detail = analyze_messages_detail(messages)
    if not detail:
        return "No messages to analyze."

    cap = breakdown.total_capacity
    lines: list[str] = [
        "Context Detail — Per-Message Breakdown",
        "━" * 50,
        "",
    ]

    # Group by category
    categories = {"system": [], "conversation": [], "tool": [], "injected": []}
    for info in detail:
        if info.category in categories:
            categories[info.category].append(info)

    cat_labels = {
        "system": "System Messages",
        "conversation": "Conversation (User ↔ Assistant)",
        "tool": "Tool Results",
        "injected": "Injected Context",
    }

    for cat_key, cat_label in cat_labels.items():
        items = categories[cat_key]
        if not items:
            continue
        total = sum(m.tokens for m in items)
        lines.append(f"  {cat_label} ({len(items)} messages, ~{_fmt_tokens(total)})")
        lines.append("  " + "─" * 46)
        # Show each message, sorted largest first (top 15)
        sorted_items = sorted(items, key=lambda m: m.tokens, reverse=True)
        for info in sorted_items[:15]:
            role_tag = info.role[:5].ljust(5)
            lines.append(
                f"    #{info.index:<4d} [{role_tag}] ~{_fmt_tokens(info.tokens):>6s}  {info.preview}"
            )
        if len(sorted_items) > 15:
            lines.append(f"    ... and {len(sorted_items) - 15} more")
        lines.append("")

    # Summary
    lines.append("─" * 50)
    lines.append(
        f"  Total: ~{_fmt_tokens(breakdown.total_used)} / {_fmt_tokens(cap)} "
        f"({breakdown.usage_percent:.1f}%)"
    )

    return "\n".join(lines)


def format_profiler_history(history: list[float]) -> str:
    """Return a sparkline of context usage percentage over time.

    *history* is a list of usage percentages (0.0–100.0) recorded after
    each message exchange.
    """
    if not history:
        return "Context History\n━━━━━━━━━━━━━━━\n  No history yet. Usage is tracked after each exchange."

    lines: list[str] = [
        "Context History — Usage Over Time",
        "━" * 40,
    ]

    # Build sparkline
    sparkline = _make_sparkline(history)
    lines.append(f"  {sparkline}")

    # Scale labels
    lines.append(f"  {'0%':<20s}{'50%':^10s}{'100%':>10s}")

    # Stats
    lines.append("")
    lines.append(f"  Data points: {len(history)}")
    lines.append(f"  Current:     {history[-1]:.1f}%")
    if len(history) > 1:
        lines.append(f"  Start:       {history[0]:.1f}%")
        delta = history[-1] - history[0]
        direction = "↑" if delta > 0 else "↓" if delta < 0 else "→"
        lines.append(f"  Change:      {direction} {abs(delta):.1f}%")

        # Growth rate
        avg_growth = delta / (len(history) - 1)
        lines.append(f"  Avg/exchange: {avg_growth:+.1f}%")

        # Estimate exchanges until full
        if avg_growth > 0:
            remaining_pct = 100.0 - history[-1]
            exchanges_left = int(remaining_pct / avg_growth)
            lines.append(f"  Est. exchanges until full: ~{exchanges_left}")

    return "\n".join(lines)


def _make_sparkline(values: list[float], max_val: float = 100.0) -> str:
    """Convert a list of floats into a sparkline string using block chars."""
    if not values:
        return ""
    chars: list[str] = []
    for v in values:
        # Normalize to 0.0–1.0 range
        normalized = max(0.0, min(1.0, v / max_val)) if max_val > 0 else 0.0
        idx = int(normalized * (len(_SPARK_CHARS) - 1))
        chars.append(_SPARK_CHARS[idx])
    return "".join(chars)


def format_top_consumers(
    messages: list[tuple[str, str, object]],
    top_n: int = 5,
) -> str:
    """Identify the N largest items consuming context."""
    detail = analyze_messages_detail(messages)
    if not detail:
        return "No messages to analyze."

    # Sort by token count, descending
    sorted_msgs = sorted(detail, key=lambda m: m.tokens, reverse=True)
    top = sorted_msgs[:top_n]

    total_all = sum(m.tokens for m in detail)

    lines: list[str] = [
        f"Top {min(top_n, len(top))} Context Consumers",
        "━" * 50,
    ]

    for rank, info in enumerate(top, 1):
        share = (info.tokens / total_all * 100) if total_all > 0 else 0.0
        role_tag = info.role[:8].ljust(8)
        lines.append(
            f"  {rank}. [{role_tag}] ~{_fmt_tokens(info.tokens):>6s}"
            f"  ({share:.1f}%)  {info.preview}"
        )

    lines.append("")
    lines.append(f"  Total tracked: ~{_fmt_tokens(total_all)}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# History tracker (stateful, one per tab)
# ---------------------------------------------------------------------------


@dataclass
class ContextHistory:
    """Tracks context usage percentage over time for sparkline display."""

    snapshots: list[float] = field(default_factory=list)

    def record(self, usage_percent: float) -> None:
        """Record a usage snapshot (call after each message exchange)."""
        self.snapshots.append(min(100.0, max(0.0, usage_percent)))

    def as_list(self) -> list[float]:
        """Return the history as a plain list."""
        return list(self.snapshots)
