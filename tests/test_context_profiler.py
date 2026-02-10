"""Tests for the context window profiler feature (F2.2)."""

from __future__ import annotations

import pytest

from amplifier_tui.features.context_profiler import (
    ContextBreakdown,
    ContextHistory,
    MessageInfo,
    _classify_role,
    _fmt_tokens,
    _make_sparkline,
    analyze_messages,
    analyze_messages_detail,
    estimate_tokens,
    format_profiler_bar,
    format_profiler_detail,
    format_profiler_history,
    format_top_consumers,
)


# ---------------------------------------------------------------------------
# estimate_tokens
# ---------------------------------------------------------------------------


class TestEstimateTokens:
    """Tests for the chars/4 token estimator."""

    def test_empty_string(self):
        assert estimate_tokens("") == 0

    def test_short_string(self):
        # "hi" is 2 chars → 2//4 = 0 → clamped to 1
        assert estimate_tokens("hi") == 1

    def test_four_chars(self):
        assert estimate_tokens("abcd") == 1

    def test_typical_sentence(self):
        text = "Hello, how are you doing today?"  # 30 chars → 7
        assert estimate_tokens(text) == 30 // 4

    def test_large_text(self):
        text = "x" * 4000  # 4000 chars → 1000
        assert estimate_tokens(text) == 1000

    def test_single_char(self):
        assert estimate_tokens("a") == 1

    def test_none_like_empty(self):
        # The function expects str, but empty string should be safe
        assert estimate_tokens("") == 0


# ---------------------------------------------------------------------------
# ContextBreakdown
# ---------------------------------------------------------------------------


class TestContextBreakdown:
    """Tests for the ContextBreakdown dataclass properties."""

    def test_total_used(self):
        bd = ContextBreakdown(
            system_tokens=100,
            conversation_tokens=200,
            tool_result_tokens=300,
            injected_context_tokens=50,
        )
        assert bd.total_used == 650

    def test_available(self):
        bd = ContextBreakdown(
            system_tokens=50_000,
            conversation_tokens=100_000,
            total_capacity=200_000,
        )
        assert bd.available == 50_000

    def test_available_when_over_capacity(self):
        bd = ContextBreakdown(
            system_tokens=150_000,
            conversation_tokens=100_000,
            total_capacity=200_000,
        )
        assert bd.available == 0  # clamped to 0

    def test_usage_percent(self):
        bd = ContextBreakdown(
            conversation_tokens=100_000,
            total_capacity=200_000,
        )
        assert bd.usage_percent == pytest.approx(50.0)

    def test_usage_percent_capped_at_100(self):
        bd = ContextBreakdown(
            conversation_tokens=300_000,
            total_capacity=200_000,
        )
        assert bd.usage_percent == 100.0

    def test_usage_percent_zero_capacity(self):
        bd = ContextBreakdown(total_capacity=0)
        assert bd.usage_percent == 0.0

    def test_warning_level_normal(self):
        bd = ContextBreakdown(
            conversation_tokens=50_000,
            total_capacity=200_000,
        )
        assert bd.warning_level == "normal"

    def test_warning_level_warning(self):
        bd = ContextBreakdown(
            conversation_tokens=160_000,
            total_capacity=200_000,
        )
        # 80% → warning (75-85%)
        assert bd.warning_level == "warning"

    def test_warning_level_danger(self):
        bd = ContextBreakdown(
            conversation_tokens=180_000,
            total_capacity=200_000,
        )
        # 90% → danger (85-95%)
        assert bd.warning_level == "danger"

    def test_warning_level_critical(self):
        bd = ContextBreakdown(
            conversation_tokens=196_000,
            total_capacity=200_000,
        )
        # 98% → critical (≥95%)
        assert bd.warning_level == "critical"

    def test_warning_level_boundary_75(self):
        bd = ContextBreakdown(
            conversation_tokens=75_000,
            total_capacity=100_000,
        )
        # Exactly 75% → warning
        assert bd.warning_level == "warning"

    def test_warning_level_boundary_85(self):
        bd = ContextBreakdown(
            conversation_tokens=85_000,
            total_capacity=100_000,
        )
        # Exactly 85% → danger
        assert bd.warning_level == "danger"

    def test_warning_level_boundary_95(self):
        bd = ContextBreakdown(
            conversation_tokens=95_000,
            total_capacity=100_000,
        )
        # Exactly 95% → critical
        assert bd.warning_level == "critical"

    def test_all_zeroes(self):
        bd = ContextBreakdown()
        assert bd.total_used == 0
        assert bd.available == 200_000
        assert bd.usage_percent == 0.0
        assert bd.warning_level == "normal"


# ---------------------------------------------------------------------------
# _classify_role
# ---------------------------------------------------------------------------


class TestClassifyRole:
    """Tests for role classification."""

    def test_system(self):
        assert _classify_role("system") == "system"

    def test_user(self):
        assert _classify_role("user") == "conversation"

    def test_assistant(self):
        assert _classify_role("assistant") == "conversation"

    def test_tool(self):
        assert _classify_role("tool") == "tool"

    def test_tool_result(self):
        assert _classify_role("tool_result") == "tool"

    def test_tool_use(self):
        assert _classify_role("tool_use") == "tool"

    def test_note(self):
        assert _classify_role("note") == "meta"

    def test_thinking(self):
        assert _classify_role("thinking") == "meta"

    def test_unknown_role(self):
        assert _classify_role("something_else") == "injected"

    def test_case_insensitive(self):
        assert _classify_role("SYSTEM") == "system"
        assert _classify_role("User") == "conversation"

    def test_whitespace_stripped(self):
        assert _classify_role("  system  ") == "system"


# ---------------------------------------------------------------------------
# analyze_messages
# ---------------------------------------------------------------------------


class TestAnalyzeMessages:
    """Tests for message analysis and categorization."""

    def test_empty_messages(self):
        bd = analyze_messages([])
        assert bd.total_used == 0
        assert bd.system_tokens == 0

    def test_system_messages(self):
        msgs = [("system", "You are a helpful assistant." * 10, None)]
        bd = analyze_messages(msgs, total_capacity=200_000)
        assert bd.system_tokens > 0
        assert bd.conversation_tokens == 0
        assert bd.tool_result_tokens == 0

    def test_conversation_messages(self):
        msgs = [
            ("user", "Hello there", None),
            ("assistant", "Hi! How can I help?", None),
        ]
        bd = analyze_messages(msgs)
        assert bd.conversation_tokens > 0
        assert bd.system_tokens == 0

    def test_tool_messages(self):
        msgs = [
            ("tool_result", '{"file": "test.py", "content": "..."}', None),
        ]
        bd = analyze_messages(msgs)
        assert bd.tool_result_tokens > 0
        assert bd.conversation_tokens == 0

    def test_mixed_messages(self):
        msgs = [
            ("system", "You are helpful.", None),
            ("user", "Read this file", None),
            ("assistant", "Sure, let me read it.", None),
            ("tool_result", '{"content": "file contents here"}', None),
            ("note", "This is a local note", None),
        ]
        bd = analyze_messages(msgs, total_capacity=200_000)
        assert bd.system_tokens > 0
        assert bd.conversation_tokens > 0
        assert bd.tool_result_tokens > 0
        # Note messages should NOT be counted
        total_without_note = (
            bd.system_tokens
            + bd.conversation_tokens
            + bd.tool_result_tokens
            + bd.injected_context_tokens
        )
        assert bd.total_used == total_without_note

    def test_capacity_passed_through(self):
        bd = analyze_messages([], total_capacity=128_000)
        assert bd.total_capacity == 128_000

    def test_none_content_handled(self):
        msgs = [("user", None, None)]
        bd = analyze_messages(msgs)
        # None content → 0 tokens
        assert bd.conversation_tokens == 0

    def test_meta_messages_excluded(self):
        msgs = [
            ("thinking", "Let me think about this...", None),
            ("note", "User seems confused", None),
        ]
        bd = analyze_messages(msgs)
        assert bd.total_used == 0


# ---------------------------------------------------------------------------
# analyze_messages_detail
# ---------------------------------------------------------------------------


class TestAnalyzeMessagesDetail:
    """Tests for per-message detail analysis."""

    def test_empty(self):
        assert analyze_messages_detail([]) == []

    def test_excludes_meta(self):
        msgs = [
            ("user", "Hello", None),
            ("thinking", "Let me think...", None),
        ]
        detail = analyze_messages_detail(msgs)
        assert len(detail) == 1
        assert detail[0].role == "user"

    def test_message_info_fields(self):
        msgs = [("assistant", "Here is a helpful response for you.", None)]
        detail = analyze_messages_detail(msgs)
        assert len(detail) == 1
        info = detail[0]
        assert isinstance(info, MessageInfo)
        assert info.index == 0
        assert info.role == "assistant"
        assert info.category == "conversation"
        assert info.tokens > 0
        assert len(info.preview) <= 80

    def test_preview_truncation(self):
        long_text = "x" * 200
        msgs = [("user", long_text, None)]
        detail = analyze_messages_detail(msgs)
        assert len(detail[0].preview) <= 80
        assert detail[0].preview.endswith("...")

    def test_preview_newlines_collapsed(self):
        text = "line one\nline two\nline three"
        msgs = [("user", text, None)]
        detail = analyze_messages_detail(msgs)
        assert "\n" not in detail[0].preview


# ---------------------------------------------------------------------------
# format_profiler_bar
# ---------------------------------------------------------------------------


class TestFormatProfilerBar:
    """Tests for the stacked bar visualization."""

    def test_basic_output_structure(self):
        bd = ContextBreakdown(
            system_tokens=24_000,
            conversation_tokens=76_000,
            tool_result_tokens=48_000,
            injected_context_tokens=20_000,
            total_capacity=200_000,
        )
        result = format_profiler_bar(bd)
        # Should contain the header with percentage
        assert "Context:" in result
        assert "%" in result
        # Should contain category labels
        assert "System prompt:" in result
        assert "Conversation:" in result
        assert "Tool results:" in result
        assert "Injected context:" in result
        assert "Available:" in result

    def test_bar_contains_category_chars(self):
        bd = ContextBreakdown(
            system_tokens=50_000,
            conversation_tokens=50_000,
            total_capacity=200_000,
        )
        result = format_profiler_bar(bd)
        lines = result.split("\n")
        bar_line = lines[0]
        # Bar should contain S for system and C for conversation
        assert "S" in bar_line
        assert "C" in bar_line
        # Available space shown with dashes
        assert "-" in bar_line

    def test_empty_breakdown(self):
        bd = ContextBreakdown(total_capacity=200_000)
        result = format_profiler_bar(bd)
        assert "0%" in result
        assert "Available:" in result

    def test_critical_warning(self):
        bd = ContextBreakdown(
            conversation_tokens=196_000,
            total_capacity=200_000,
        )
        result = format_profiler_bar(bd)
        assert "nearly full" in result.lower() or "🔴" in result

    def test_danger_warning(self):
        bd = ContextBreakdown(
            conversation_tokens=180_000,
            total_capacity=200_000,
        )
        result = format_profiler_bar(bd)
        assert "getting full" in result.lower() or "⚠" in result

    def test_warning_level_message(self):
        bd = ContextBreakdown(
            conversation_tokens=160_000,
            total_capacity=200_000,
        )
        result = format_profiler_bar(bd)
        assert "elevated" in result.lower() or "⚠" in result

    def test_custom_width(self):
        bd = ContextBreakdown(
            conversation_tokens=100_000,
            total_capacity=200_000,
        )
        result = format_profiler_bar(bd, width=30)
        bar_line = result.split("\n")[0]
        # Bar is between [ and ]
        start = bar_line.index("[")
        end = bar_line.index("]")
        bar_content = bar_line[start + 1 : end]
        assert len(bar_content) == 30

    def test_percentages_shown(self):
        bd = ContextBreakdown(
            system_tokens=20_000,
            conversation_tokens=80_000,
            total_capacity=200_000,
        )
        result = format_profiler_bar(bd)
        # Should show percentage for each category
        assert "10.0%" in result  # system: 20k/200k = 10%
        assert "40.0%" in result  # conversation: 80k/200k = 40%


# ---------------------------------------------------------------------------
# format_profiler_detail
# ---------------------------------------------------------------------------


class TestFormatProfilerDetail:
    """Tests for the detailed per-message breakdown."""

    def test_empty_messages(self):
        bd = ContextBreakdown()
        result = format_profiler_detail([], bd)
        assert "No messages" in result

    def test_detail_output_structure(self):
        msgs = [
            ("system", "You are helpful.", None),
            ("user", "Hello", None),
            ("assistant", "Hi there!", None),
        ]
        bd = analyze_messages(msgs)
        result = format_profiler_detail(msgs, bd)
        assert "Per-Message Breakdown" in result
        assert "System Messages" in result
        assert "Conversation" in result
        assert "Total:" in result

    def test_detail_shows_message_indices(self):
        msgs = [
            ("user", "First message", None),
            ("assistant", "Second message", None),
        ]
        bd = analyze_messages(msgs)
        result = format_profiler_detail(msgs, bd)
        assert "#0" in result
        assert "#1" in result

    def test_detail_excludes_meta(self):
        msgs = [
            ("user", "Hello", None),
            ("thinking", "Internal thought", None),
        ]
        bd = analyze_messages(msgs)
        result = format_profiler_detail(msgs, bd)
        assert "thinking" not in result.lower() or "Internal thought" not in result


# ---------------------------------------------------------------------------
# format_profiler_history
# ---------------------------------------------------------------------------


class TestFormatProfilerHistory:
    """Tests for the sparkline history display."""

    def test_empty_history(self):
        result = format_profiler_history([])
        assert "No history" in result

    def test_single_point(self):
        result = format_profiler_history([25.0])
        assert "Current:" in result
        assert "25.0%" in result

    def test_multiple_points(self):
        history = [10.0, 20.0, 30.0, 40.0, 50.0]
        result = format_profiler_history(history)
        assert "Data points: 5" in result
        assert "Start:" in result
        assert "Change:" in result
        assert "Avg/exchange:" in result

    def test_growing_history_shows_estimate(self):
        history = [10.0, 20.0, 30.0, 40.0]
        result = format_profiler_history(history)
        # Should show estimated exchanges until full
        assert "Est. exchanges until full:" in result

    def test_declining_history_no_estimate(self):
        history = [50.0, 40.0, 30.0, 20.0]
        result = format_profiler_history(history)
        # Declining usage should NOT show estimate
        assert "Est. exchanges until full:" not in result

    def test_sparkline_chars_present(self):
        history = [0.0, 25.0, 50.0, 75.0, 100.0]
        result = format_profiler_history(history)
        # Should contain sparkline block characters
        spark_chars = set("▁▂▃▄▅▆▇█")
        has_spark = any(c in spark_chars for c in result)
        assert has_spark


# ---------------------------------------------------------------------------
# _make_sparkline
# ---------------------------------------------------------------------------


class TestMakeSparkline:
    """Tests for the sparkline helper."""

    def test_empty(self):
        assert _make_sparkline([]) == ""

    def test_all_zeros(self):
        result = _make_sparkline([0.0, 0.0, 0.0])
        assert result == "▁▁▁"

    def test_all_max(self):
        result = _make_sparkline([100.0, 100.0])
        assert result == "██"

    def test_ascending(self):
        result = _make_sparkline([0.0, 50.0, 100.0])
        assert len(result) == 3
        # Should be ascending block chars
        assert result[0] <= result[1] <= result[2]

    def test_custom_max(self):
        result = _make_sparkline([5.0, 10.0], max_val=10.0)
        assert len(result) == 2
        # 5/10 = 0.5, 10/10 = 1.0
        assert result[1] == "█"

    def test_zero_max_val(self):
        result = _make_sparkline([5.0], max_val=0.0)
        assert result == "▁"


# ---------------------------------------------------------------------------
# format_top_consumers
# ---------------------------------------------------------------------------


class TestFormatTopConsumers:
    """Tests for the top consumers display."""

    def test_empty_messages(self):
        result = format_top_consumers([])
        assert "No messages" in result

    def test_identifies_largest(self):
        msgs = [
            ("user", "short", None),
            ("assistant", "x" * 4000, None),  # ~1000 tokens
            ("user", "medium length message here", None),
        ]
        result = format_top_consumers(msgs, top_n=3)
        assert "Top 3" in result
        lines = result.split("\n")
        # First ranked item should be the long assistant message
        ranked_lines = [l for l in lines if l.strip().startswith("1.")]
        assert len(ranked_lines) == 1
        assert "assistan" in ranked_lines[0]

    def test_top_n_limit(self):
        msgs = [(f"user", f"message {i}" * 10, None) for i in range(20)]
        result = format_top_consumers(msgs, top_n=5)
        assert "Top 5" in result
        # Should only show 5 ranked items
        ranked = [l for l in result.split("\n") if l.strip()[:2] in ("1.", "2.", "3.", "4.", "5.")]
        assert len(ranked) == 5

    def test_shows_percentage(self):
        msgs = [
            ("user", "x" * 400, None),
            ("assistant", "y" * 400, None),
        ]
        result = format_top_consumers(msgs, top_n=2)
        assert "%" in result

    def test_shows_total(self):
        msgs = [("user", "Hello world", None)]
        result = format_top_consumers(msgs)
        assert "Total tracked:" in result


# ---------------------------------------------------------------------------
# ContextHistory
# ---------------------------------------------------------------------------


class TestContextHistory:
    """Tests for the stateful history tracker."""

    def test_empty_initial(self):
        h = ContextHistory()
        assert h.as_list() == []

    def test_record_values(self):
        h = ContextHistory()
        h.record(10.0)
        h.record(25.0)
        h.record(40.0)
        assert h.as_list() == [10.0, 25.0, 40.0]

    def test_clamps_to_range(self):
        h = ContextHistory()
        h.record(-5.0)
        h.record(150.0)
        assert h.as_list() == [0.0, 100.0]

    def test_as_list_returns_copy(self):
        h = ContextHistory()
        h.record(50.0)
        result = h.as_list()
        result.append(999.0)
        assert h.as_list() == [50.0]  # original unchanged


# ---------------------------------------------------------------------------
# _fmt_tokens
# ---------------------------------------------------------------------------


class TestFmtTokens:
    """Tests for the token count formatter."""

    def test_small_number(self):
        assert _fmt_tokens(500) == "500"

    def test_thousands(self):
        assert _fmt_tokens(1_500) == "1.5k"

    def test_tens_of_thousands(self):
        assert _fmt_tokens(24_000) == "24.0k"

    def test_hundreds_of_thousands(self):
        assert _fmt_tokens(200_000) == "200k"

    def test_millions(self):
        assert _fmt_tokens(1_500_000) == "1.5M"

    def test_zero(self):
        assert _fmt_tokens(0) == "0"

    def test_exact_thousand(self):
        assert _fmt_tokens(1_000) == "1.0k"


# ---------------------------------------------------------------------------
# Integration test: full pipeline
# ---------------------------------------------------------------------------


class TestProfilerPipeline:
    """End-to-end tests combining analysis + formatting."""

    def test_full_pipeline(self):
        """Analyze messages → format bar → verify output."""
        msgs = [
            ("system", "You are a helpful coding assistant." * 50, None),
            ("user", "Please help me with Python", None),
            ("assistant", "Of course! Python is great." * 100, None),
            ("tool_result", '{"file": "main.py", "content": "..."}' * 20, None),
            ("user", "Thanks, now read another file", None),
            ("assistant", "Sure, here it is." * 50, None),
        ]

        bd = analyze_messages(msgs, total_capacity=200_000)

        # Verify breakdown categories
        assert bd.system_tokens > 0
        assert bd.conversation_tokens > 0
        assert bd.tool_result_tokens > 0
        assert bd.total_used > 0
        assert bd.total_used < bd.total_capacity
        assert bd.available > 0

        # Verify bar format
        bar = format_profiler_bar(bd)
        assert "Context:" in bar
        assert "System prompt:" in bar

        # Verify detail format
        detail = format_profiler_detail(msgs, bd)
        assert "Per-Message Breakdown" in detail

        # Verify top consumers
        top = format_top_consumers(msgs, top_n=3)
        assert "Top 3" in top

    def test_pipeline_with_sample_messages(self, sample_messages):
        """Use the conftest sample_messages fixture."""
        bd = analyze_messages(sample_messages, total_capacity=200_000)
        assert bd.conversation_tokens > 0
        assert bd.system_tokens == 0  # sample has no system messages

        bar = format_profiler_bar(bd)
        assert "Context:" in bar

    def test_pipeline_with_history(self):
        """Verify history tracking integrates with analysis."""
        history = ContextHistory()

        for i in range(5):
            # Simulate growing context
            msgs = [("user", f"msg {j}" * 100, None) for j in range(i + 1)]
            bd = analyze_messages(msgs, total_capacity=200_000)
            history.record(bd.usage_percent)

        result = format_profiler_history(history.as_list())
        assert "Data points: 5" in result
        assert "Start:" in result
