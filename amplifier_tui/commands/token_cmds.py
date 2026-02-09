"""Token usage, stats, and context window commands."""

from __future__ import annotations

from pathlib import Path
import time


from .._utils import _context_color_name
from ..constants import (
    TOOL_LABELS,
)
from ..preferences import (
    save_context_window_size,
    save_show_token_usage,
)


class TokenCommandsMixin:
    """Token usage, stats, and context window commands."""

    def _cmd_keys(self) -> None:
        """Show the keyboard shortcut overlay."""
        self.action_show_shortcuts()

    def _cmd_stats(self, text: str = "") -> None:
        """Show session statistics, or a subcommand view.

        Subcommands:
            /stats          Full overview
            /stats tools    Detailed tool usage breakdown
            /stats tokens   Detailed token breakdown with cost estimate
            /stats time     Detailed timing metrics
        """
        sub = text.strip().lower()

        if sub == "tools":
            self._cmd_stats_tools()
            return
        if sub == "tokens":
            self._cmd_stats_tokens()
            return
        if sub == "time":
            self._cmd_stats_time()
            return
        if sub:
            self._add_system_message(
                f"Unknown subcommand: /stats {sub}\n"
                "Usage: /stats | /stats tools | /stats tokens | /stats time"
            )
            return

        fmt = self._format_token_count

        # --- Duration ---
        elapsed = time.monotonic() - self._session_start_time
        if elapsed < 60:
            duration = f"{int(elapsed)}s"
        elif elapsed < 3600:
            duration = f"{int(elapsed / 60)}m"
        else:
            hours = int(elapsed / 3600)
            mins = int((elapsed % 3600) / 60)
            duration = f"{hours}h {mins}m"

        # --- Session / model ---
        session_id = "none"
        model = "unknown"
        if self.session_manager:
            sid = getattr(self.session_manager, "session_id", None) or ""
            session_id = sid[:12] if sid else "none"
            model = getattr(self.session_manager, "model_name", None) or "unknown"

        # --- Message counts ---
        total_msgs = self._user_message_count + self._assistant_message_count

        # --- Word counts ---
        user_w = self._format_count(self._user_words)
        asst_w = self._format_count(self._assistant_words)

        # --- Character counts & code blocks from _search_messages ---
        user_chars = 0
        asst_chars = 0
        code_blocks = 0
        system_count = 0
        for role, content, _widget in self._search_messages:
            r = role.lower()
            if r == "user":
                user_chars += len(content or "")
            elif r == "assistant":
                asst_chars += len(content or "")
                if content:
                    code_blocks += content.count("```") // 2
            elif r == "system":
                system_count += 1
        total_chars = user_chars + asst_chars

        # --- Token estimates (words * 1.3) ---
        total_words = self._user_words + self._assistant_words
        est_tokens = int(total_words * 1.3)

        # --- Title ---
        title = getattr(self, "_session_title", "") or ""

        # --- Build output ---
        lines: list[str] = [
            "Session Statistics",
            "─" * 40,
            f"  Session:         {session_id}",
        ]
        if title:
            lines.append(f"  Title:           {title}")
        lines += [
            f"  Model:           {model}",
            f"  Duration:        {duration}",
            "",
            f"  Messages:        {total_msgs} total",
            f"    You:           {self._user_message_count} ({user_w} words)",
            f"    AI:            {self._assistant_message_count} ({asst_w} words)",
            f"    System:        {system_count}",
            f"    Tool calls:    {self._tool_call_count}",
            "",
            f"  Characters:      {total_chars:,}",
            f"    You:           {user_chars:,}",
            f"    AI:            {asst_chars:,}",
            f"  Est. tokens:     ~{fmt(est_tokens)}",
        ]

        if code_blocks:
            lines.append(f"  Code blocks:     {code_blocks}")

        # Real API token data from session manager
        sm = self.session_manager
        if sm:
            inp_tok = getattr(sm, "total_input_tokens", 0) or 0
            out_tok = getattr(sm, "total_output_tokens", 0) or 0
            if inp_tok or out_tok:
                lines.append(
                    f"  API tokens:      {fmt(inp_tok)} in / {fmt(out_tok)} out"
                )
                # Context usage percentage
                window = self._get_context_window()
                if window > 0:
                    pct = min(100.0, inp_tok / window * 100)
                    lines.append(f"  Context:         {pct:.1f}% of {fmt(window)}")
                # Cost estimate summary (Claude Sonnet pricing)
                cost_in = inp_tok * 3.0 / 1_000_000
                cost_out = out_tok * 15.0 / 1_000_000
                cost_total = cost_in + cost_out
                lines.append(f"  Est. cost:       ${cost_total:.4f}")

        # --- Response times ---
        if self._response_times:
            times = self._response_times
            avg_t = sum(times) / len(times)
            min_t = min(times)
            max_t = max(times)
            lines.append("")
            lines.append(f"  Response times:  {len(times)} requests")
            lines.append(f"    Avg:           {avg_t:.1f}s")
            lines.append(f"    Min:           {min_t:.1f}s")
            lines.append(f"    Max:           {max_t:.1f}s")

        # --- Top tools ---
        if self._tool_usage:
            lines.append("")
            lines.append("  Top tools:")
            sorted_tools = sorted(self._tool_usage.items(), key=lambda x: -x[1])
            for name, count in sorted_tools[:5]:
                label = TOOL_LABELS.get(name, name)
                lines.append(f"    {label:<20s} {count}")
            if len(self._tool_usage) > 5:
                lines.append(
                    f"    ... {len(self._tool_usage) - 5} more "
                    "(use /stats tools for full list)"
                )

        # --- Top words ---
        top = self._top_words(self._search_messages)
        if top:
            lines.append("")
            lines.append("  Top words:")
            for word, cnt in top:
                lines.append(f"    {word:<18s} {cnt}")

        lines.append("")
        lines.append("Tip: /stats tools | /stats tokens | /stats time")

        self._add_system_message("\n".join(lines))

    def _cmd_stats_tools(self) -> None:
        """Show detailed tool usage breakdown."""
        if not self._tool_usage:
            self._add_system_message("No tools used in this session yet.")
            return

        sorted_tools = sorted(self._tool_usage.items(), key=lambda x: -x[1])
        total_calls = sum(self._tool_usage.values())

        lines: list[str] = [
            "Tool Usage Breakdown",
            "─" * 40,
        ]

        for name, count in sorted_tools:
            label = TOOL_LABELS.get(name, name)
            pct = count / total_calls * 100
            bar_w = 15
            filled = int(pct / 100 * bar_w)
            bar = "█" * filled + "░" * (bar_w - filled)
            lines.append(f"  {label:<20s} {count:3d}  {bar} {pct:4.1f}%")

        lines += [
            "",
            f"  Total:             {total_calls:3d} calls",
            f"  Unique tools:      {len(self._tool_usage):3d}",
        ]

        self._add_system_message("\n".join(lines))

    def _cmd_stats_tokens(self) -> None:
        """Show detailed token breakdown with cost estimate."""
        fmt = self._format_token_count
        sm = self.session_manager

        inp_tok = (getattr(sm, "total_input_tokens", 0) or 0) if sm else 0
        out_tok = (getattr(sm, "total_output_tokens", 0) or 0) if sm else 0
        api_total = inp_tok + out_tok

        # Word-based estimates
        total_words = self._user_words + self._assistant_words
        est_tokens = int(total_words * 1.3)

        # Context window
        window = self._get_context_window()
        model = (sm.model_name if sm else "") or "unknown"

        lines: list[str] = [
            "Token Breakdown",
            "─" * 40,
            f"  Model:             {model}",
            f"  Context window:    {fmt(window)}",
            "",
        ]

        if api_total > 0:
            pct_in = inp_tok / api_total * 100 if api_total else 0
            pct_out = out_tok / api_total * 100 if api_total else 0
            ctx_pct = min(100.0, inp_tok / window * 100) if window > 0 else 0

            lines += [
                "  API Tokens (actual)",
                "  " + "─" * 20,
                f"  Input:             {inp_tok:>10,}  ({pct_in:.1f}%)",
                f"  Output:            {out_tok:>10,}  ({pct_out:.1f}%)",
                f"  Total:             {api_total:>10,}",
                f"  Context used:      {ctx_pct:.1f}%",
                "",
            ]

            # Cost estimate (Claude Sonnet pricing: $3/M input, $15/M output)
            cost_in = inp_tok * 3.0 / 1_000_000
            cost_out = out_tok * 15.0 / 1_000_000
            cost_total = cost_in + cost_out
            lines += [
                "  Estimated Cost (Sonnet pricing)",
                "  " + "─" * 33,
                f"  Input  ($3/M):     ${cost_in:.4f}",
                f"  Output ($15/M):    ${cost_out:.4f}",
                f"  Total:             ${cost_total:.4f}",
                "",
            ]
        else:
            lines.append("  (no API token data yet)")
            lines.append("")

        lines += [
            "  Word-based Estimate",
            "  " + "─" * 21,
            f"  User words:        {self._user_words:>10,}",
            f"  Assistant words:   {self._assistant_words:>10,}",
            f"  Total words:       {total_words:>10,}",
            f"  Est. tokens:       ~{fmt(est_tokens)}  (words × 1.3)",
        ]

        self._add_system_message("\n".join(lines))

    def _cmd_stats_time(self) -> None:
        """Show detailed timing metrics."""
        elapsed = time.monotonic() - self._session_start_time

        # Format duration nicely
        if elapsed < 60:
            duration = f"{elapsed:.0f}s"
        elif elapsed < 3600:
            m, s = divmod(int(elapsed), 60)
            duration = f"{m}m {s}s"
        else:
            h, rem = divmod(int(elapsed), 3600)
            m, s = divmod(rem, 60)
            duration = f"{h}h {m}m {s}s"

        lines: list[str] = [
            "Timing Metrics",
            "\u2500" * 40,
            f"  Session duration:  {duration}",
        ]

        total_msgs = self._user_message_count + self._assistant_message_count
        if total_msgs > 0:
            avg_interval = elapsed / total_msgs
            if avg_interval < 60:
                interval_str = f"{avg_interval:.1f}s"
            else:
                interval_str = f"{avg_interval / 60:.1f}m"
            lines.append(f"  Avg msg interval: {interval_str}")

        if self._response_times:
            times = self._response_times
            avg_t = sum(times) / len(times)
            min_t = min(times)
            max_t = max(times)
            total_wait = sum(times)
            median_t = sorted(times)[len(times) // 2]

            lines += [
                "",
                f"  Responses:         {len(times)} requests",
                f"  Total wait:        {total_wait:.1f}s",
                "",
                "  Response Time Distribution",
                "  " + "\u2500" * 28,
                f"    Min:             {min_t:.1f}s",
                f"    Median:          {median_t:.1f}s",
                f"    Avg:             {avg_t:.1f}s",
                f"    Max:             {max_t:.1f}s",
            ]

            # Standard deviation
            if len(times) > 1:
                mean = avg_t
                variance = sum((t - mean) ** 2 for t in times) / (len(times) - 1)
                std_dev = variance**0.5
                lines.append(f"    Std dev:         {std_dev:.1f}s")

            # Histogram buckets
            if len(times) >= 3:
                buckets = [
                    ("< 2s", 0, 2),
                    ("2-5s", 2, 5),
                    ("5-10s", 5, 10),
                    ("10-30s", 10, 30),
                    ("> 30s", 30, float("inf")),
                ]
                lines.append("")
                lines.append("  Response Histogram")
                lines.append("  " + "\u2500" * 28)
                for label, lo, hi in buckets:
                    n = sum(1 for t in times if lo <= t < hi)
                    if n > 0:
                        bar_w = 12
                        filled = max(1, int(n / len(times) * bar_w))
                        bar = "\u2588" * filled + "\u2591" * (bar_w - filled)
                        lines.append(f"    {label:<8s} {n:3d}  {bar}")

            # Time trend (first half vs second half)
            if len(times) >= 4:
                mid = len(times) // 2
                first_avg = sum(times[:mid]) / mid
                second_avg = sum(times[mid:]) / (len(times) - mid)
                if second_avg < first_avg * 0.9:
                    trend = "\u2193 getting faster"
                elif second_avg > first_avg * 1.1:
                    trend = "\u2191 getting slower"
                else:
                    trend = "\u2192 stable"
                lines += [
                    "",
                    f"  Trend:             {trend}",
                    f"    First half avg:  {first_avg:.1f}s",
                    f"    Second half avg: {second_avg:.1f}s",
                ]
        else:
            lines += [
                "",
                "  (no response times recorded yet)",
            ]

        self._add_system_message("\n".join(lines))

    def _cmd_info(self) -> None:
        """Show comprehensive session information."""
        session_id = self._get_session_id()
        if not session_id:
            self._add_system_message("No active session")
            return

        sm = self.session_manager
        names = self._load_session_names()
        pins = self._pinned_sessions
        bookmarks = self._load_bookmarks()

        # Gather info
        custom_name = names.get(session_id, "")
        is_pinned = session_id in pins
        bookmark_count = len(bookmarks.get(session_id, []))

        # Message counts
        user_msgs = self._user_message_count
        asst_msgs = self._assistant_message_count
        total_msgs = user_msgs + asst_msgs
        tool_calls = self._tool_call_count

        # Token info from session manager
        input_tokens = getattr(sm, "total_input_tokens", 0) if sm else 0
        output_tokens = getattr(sm, "total_output_tokens", 0) if sm else 0
        context_window = getattr(sm, "context_window", 0) if sm else 0

        # Word-based estimate as fallback
        total_words = self._user_words + self._assistant_words
        est_tokens = int(total_words * 1.3)

        # Model info
        model = (getattr(sm, "model_name", "") if sm else "") or ""
        preferred = getattr(self._prefs, "preferred_model", "")
        model_display = model or preferred or "unknown"

        # Project directory
        project = str(Path.cwd())

        # Duration
        elapsed = time.monotonic() - self._session_start_time
        if elapsed < 60:
            duration = f"{int(elapsed)} seconds"
        elif elapsed < 3600:
            duration = f"{int(elapsed / 60)} minutes"
        else:
            hours = int(elapsed / 3600)
            mins = int((elapsed % 3600) / 60)
            duration = f"{hours}h {mins}m"

        # Build display
        lines = [
            "Session Information",
            "\u2500" * 40,
            f"  ID:          {session_id[:12]}{'...' if len(session_id) > 12 else ''}",
        ]

        if custom_name:
            lines.append(f"  Name:        {custom_name}")

        lines.extend(
            [
                f"  Model:       {model_display}",
                f"  Project:     {project}",
                f"  Duration:    {duration}",
                f"  Pinned:      {'Yes' if is_pinned else 'No'}",
                f"  Bookmarks:   {bookmark_count}",
                "",
                f"  Messages:    {total_msgs} total",
                f"    User:      {user_msgs}",
                f"    Assistant: {asst_msgs}",
                f"  Tool calls:  {tool_calls}",
            ]
        )

        # Show actual token usage if available, otherwise estimate
        if input_tokens or output_tokens:
            lines.append(
                f"  Tokens:      {input_tokens:,} in \u00b7 {output_tokens:,} out"
            )
            if context_window:
                lines.append(f"  Context:     {context_window:,} window")
        else:
            lines.append(f"  Est. tokens: ~{est_tokens:,}")

        # Theme and sort info
        theme = getattr(self._prefs, "theme_name", "dark")
        sort_mode = getattr(self._prefs, "session_sort", "date")
        lines.extend(
            [
                "",
                f"  Theme:       {theme}",
                f"  Sort:        {sort_mode}",
            ]
        )

        self._add_system_message("\n".join(lines))

    def _cmd_tokens(self) -> None:
        """Show detailed token / context usage breakdown."""
        sm = self.session_manager
        model = (sm.model_name if sm else "") or "unknown"
        window = self._get_context_window()

        # Real API-reported tokens (accumulated from llm:response hooks)
        input_tok = sm.total_input_tokens if sm else 0
        output_tok = sm.total_output_tokens if sm else 0
        api_total = input_tok + output_tok

        # Character-based estimate from visible messages
        user_chars = sum(len(t) for r, t, _w in self._search_messages if r == "user")
        asst_chars = sum(
            len(t) for r, t, _w in self._search_messages if r == "assistant"
        )
        sys_chars = sum(len(t) for r, t, _w in self._search_messages if r == "system")
        est_user = user_chars // 4
        est_asst = asst_chars // 4
        est_sys = sys_chars // 4
        est_total = est_user + est_asst + est_sys

        # Prefer real API tokens when available; fall back to estimate
        display_total = api_total if api_total > 0 else est_total
        pct = min(100.0, (display_total / window * 100)) if window > 0 else 0.0

        # Visual progress bar (20 chars wide)
        bar_width = 20
        filled = int(pct / 100 * bar_width)
        bar = "\u2588" * filled + "\u2591" * (bar_width - filled)

        # Message counts
        msg_count = len(self._search_messages)
        user_msg_count = sum(1 for r, _, _ in self._search_messages if r == "user")
        asst_msg_count = sum(1 for r, _, _ in self._search_messages if r == "assistant")
        sys_msg_count = sum(1 for r, _, _ in self._search_messages if r == "system")

        fmt = self._format_token_count
        source = "API" if api_total > 0 else "estimated"

        lines = [
            f"Context Usage  [{bar}] {pct:.0f}%",
            "\u2500" * 40,
            f"  Model:       {model}",
            f"  Window:      {fmt(window)} tokens",
            f"  Used:        ~{fmt(display_total)} tokens ({source})",
            f"  Remaining:   ~{fmt(max(0, window - display_total))} tokens",
        ]

        if api_total > 0:
            lines += [
                "",
                "API tokens:",
                f"  Input:       ~{fmt(input_tok)}",
                f"  Output:      ~{fmt(output_tok)}",
                f"  Total:       ~{fmt(api_total)}",
            ]

        # Rough cost estimate (~$3/1M input, ~$15/1M output for Claude 3.5)
        input_cost = (est_user + est_sys) / 1_000_000 * 3.0
        output_cost = est_asst / 1_000_000 * 15.0
        if api_total > 0:
            input_cost = input_tok / 1_000_000 * 3.0
            output_cost = output_tok / 1_000_000 * 15.0
        total_cost = input_cost + output_cost

        lines += [
            "",
            "Breakdown (~4 chars/token):",
            f"  User:        ~{fmt(est_user)} tokens  ({user_msg_count} messages)",
            f"  Assistant:   ~{fmt(est_asst)} tokens  ({asst_msg_count} messages)",
            f"  System:      ~{fmt(est_sys)} tokens  ({sys_msg_count} messages)",
            "",
            f"Messages: {msg_count} total",
            f"  Est. cost:   ~${total_cost:.4f}"
            f" (in ~${input_cost:.4f} + out ~${output_cost:.4f})",
            "",
            "Note: Token counts are estimates (~4 chars/token).",
            "Cost assumes Claude 3.5 Sonnet pricing ($3/1M in, $15/1M out).",
            "Actual usage may vary by model tokenizer. Context also",
            "includes system prompts, tool schemas, and overhead",
            "(typically ~10-20K tokens). Use /compact to free space.",
        ]
        self._add_system_message("\n".join(lines))

    def _cmd_context(self) -> None:
        """Show visual context window usage with a progress bar."""
        sm = self.session_manager
        model = (sm.model_name if sm else "") or "unknown"
        window = self._get_context_window()
        fmt = self._format_token_count

        # --- Gather token counts (prefer real API data) ---
        input_tokens = 0
        output_tokens = 0

        if sm:
            input_tokens = getattr(sm, "total_input_tokens", 0) or 0
            output_tokens = getattr(sm, "total_output_tokens", 0) or 0

        # Fallback: estimate from visible message text (~4 chars/token)
        estimated = False
        if input_tokens == 0 and output_tokens == 0:
            estimated = True
            for role, content, _widget in self._search_messages:
                tok_est = len(content) // 4
                if role == "user":
                    input_tokens += tok_est
                elif role == "assistant":
                    output_tokens += tok_est
                else:
                    input_tokens += tok_est  # system msgs count toward input

        total = input_tokens + output_tokens

        # Input tokens are the best proxy for how full the context window is
        # (each request sends the full conversation as input).
        effective_used = input_tokens
        pct = min(100.0, (effective_used / window * 100)) if window > 0 else 0.0

        # --- Visual bar (30 chars wide) ---
        bar_width = 30
        filled = int(pct / 100 * bar_width)
        empty = bar_width - filled

        color_label = _context_color_name(pct)

        bar = f"[{'█' * filled}{'░' * empty}]"

        # --- Build output ---
        source = "estimated" if estimated else "API"
        lines = [
            "Context Usage",
            "\u2500" * 40,
            f"  Model:     {model}",
            f"  Window:    {fmt(window)} tokens",
            "",
            f"  {bar} {pct:.1f}%",
            "",
            f"  Input:     ~{fmt(input_tokens)} ({source})",
            f"  Output:    ~{fmt(output_tokens)} ({source})",
            f"  Total:     ~{fmt(total)}",
            f"  Remaining: ~{fmt(max(0, window - effective_used))}",
        ]

        if pct > 90:
            lines += [
                "",
                "  \u26a0 Context nearly full! Start a new session with /new.",
            ]
        elif pct > 75:
            lines += [
                "",
                f"  \u26a0 Context is getting full ({color_label}). Consider /clear or /new.",
            ]

        self._add_system_message("\n".join(lines))

    def _cmd_showtokens(self, text: str) -> None:
        """Toggle the status-bar token/context usage display on or off."""
        parts = text.strip().split(None, 1)
        arg = parts[1].strip().lower() if len(parts) > 1 else ""

        if arg in ("on", "true", "1"):
            enabled = True
        elif arg in ("off", "false", "0"):
            enabled = False
        elif not arg:
            enabled = not self._prefs.display.show_token_usage
        else:
            self._add_system_message("Usage: /showtokens [on|off]")
            return

        self._prefs.display.show_token_usage = enabled
        save_show_token_usage(enabled)
        self._update_token_display()

        state = "ON" if enabled else "OFF"
        self._add_system_message(f"Token usage display: {state}")

    def _cmd_contextwindow(self, text: str) -> None:
        """Set the context window size override (0 = auto-detect)."""
        parts = text.strip().split(None, 1)
        arg = parts[1].strip().lower() if len(parts) > 1 else ""

        if not arg:
            current = self._prefs.display.context_window_size
            effective = self._get_context_window()
            if current > 0:
                self._add_system_message(
                    f"Context window: {current:,} tokens (user override)\n"
                    f"Use /contextwindow auto to auto-detect from model.\n"
                    f"Use /contextwindow <number> to set a custom size."
                )
            else:
                self._add_system_message(
                    f"Context window: {effective:,} tokens (auto-detected)\n"
                    f"Use /contextwindow <number> to override (e.g. 128000).\n"
                    f"Use /contextwindow auto to reset to auto-detect."
                )
            return

        if arg in ("auto", "0", "reset"):
            size = 0
        else:
            try:
                # Accept shorthand like "128k" or "200K"
                if arg.endswith("k"):
                    size = int(float(arg[:-1]) * 1_000)
                elif arg.endswith("m"):
                    size = int(float(arg[:-1]) * 1_000_000)
                else:
                    size = int(arg)
            except ValueError:
                self._add_system_message(
                    "Usage: /contextwindow <size|auto>\n"
                    "Examples: /contextwindow 128000, /contextwindow 128k, "
                    "/contextwindow auto"
                )
                return

        self._prefs.display.context_window_size = size
        save_context_window_size(size)
        self._update_token_display()

        if size > 0:
            self._add_system_message(
                f"Context window set to {size:,} tokens (user override)"
            )
        else:
            effective = self._get_context_window()
            self._add_system_message(
                f"Context window: auto-detect ({effective:,} tokens)"
            )

