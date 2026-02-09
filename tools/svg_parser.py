"""Parse Textual SVG screenshots into structured data.

Textual exports SVG with exact text content, positions, colors, and styles.
This is far superior to OCR for TUI analysis because:
  - Pixel-perfect text extraction (no ML uncertainty)
  - Exact color/style info per text span
  - Line-by-line layout with precise coordinates
  - Zero heavy dependencies (just stdlib xml.etree)

Usage:
    from tools.svg_parser import parse_tui_svg
    result = parse_tui_svg("/tmp/tui_capture.svg")
    # result is a dict ready for YAML output
"""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any


def parse_tui_svg(svg_path: str) -> dict[str, Any]:
    """Parse a Textual SVG screenshot into structured data.

    Returns a dict with:
      - dimensions: viewBox width/height
      - styles: CSS class -> color/style mapping
      - lines: list of lines, each with text spans (content, x, color, style)
      - layout: detected regions (header, content, input, status bar)
      - theme: color usage summary
    """
    svg_text = Path(svg_path).read_text(encoding="utf-8")

    # Extract viewBox dimensions
    dims = _parse_viewbox(svg_text)

    # Extract CSS style rules (class -> fill color, font styles)
    styles = _parse_styles(svg_text)

    # Extract text elements organized by line
    lines = _parse_text_elements(svg_text, styles)

    # Classify lines into layout regions
    layout = _classify_layout(lines, dims)

    # Build color theme from style usage
    theme = _build_theme(lines, styles)

    return {
        "dimensions": dims,
        "styles": styles,
        "lines": lines,
        "layout": layout,
        "theme": theme,
    }


def _parse_viewbox(svg_text: str) -> dict[str, float]:
    """Extract dimensions from SVG viewBox."""
    match = re.search(r'viewBox="([^"]+)"', svg_text)
    if match:
        parts = match.group(1).split()
        return {
            "width": float(parts[2]),
            "height": float(parts[3]),
        }
    return {"width": 0, "height": 0}


def _parse_styles(svg_text: str) -> dict[str, dict[str, str]]:
    """Extract CSS class definitions from <style> block.

    Returns: { "r1": {"fill": "#c5c8c6"}, "r6": {"fill": "#8877aa", "font-style": "italic"}, ... }
    """
    styles: dict[str, dict[str, str]] = {}

    # Find the style block
    style_match = re.search(r"<style>(.*?)</style>", svg_text, re.DOTALL)
    if not style_match:
        return styles

    style_text = style_match.group(1)

    # Parse rules like: .terminal-158958201-r6 { fill: #8877aa;font-style: italic; }
    # We extract just the "r6" part as the key
    rule_pattern = re.compile(r"\.terminal-\d+-r(\d+)\s*\{([^}]+)\}", re.MULTILINE)

    for match in rule_pattern.finditer(style_text):
        rule_id = f"r{match.group(1)}"
        props_str = match.group(2).strip()

        props: dict[str, str] = {}
        for prop in props_str.split(";"):
            prop = prop.strip()
            if ":" in prop:
                key, val = prop.split(":", 1)
                props[key.strip()] = val.strip()

        styles[rule_id] = props

    return styles


def _parse_text_elements(
    svg_text: str, styles: dict[str, dict[str, str]]
) -> list[dict[str, Any]]:
    """Extract text elements organized by terminal line.

    Each line is: {
        "line_num": 0,
        "y": 20.0,
        "spans": [
            {"text": "Hello world", "x": 48.8, "width": 134.2,
             "class": "r4", "color": "#ffffff", "bold": False, "italic": False}
        ]
    }
    """
    # Parse all <text> elements using regex (faster than full XML parse for this structure)
    # Pattern: <text class="terminal-HASH-rN" x="X" y="Y" textLength="W" clip-path="url(#...line-N)">CONTENT</text>
    text_pattern = re.compile(
        r'<text\s+class="terminal-\d+-r(\d+)"\s+'
        r'x="([\d.]+)"\s+y="([\d.]+)"\s+'
        r'textLength="([\d.]+)"\s+'
        r'clip-path="url\(#terminal-\d+-line-(\d+)\)">'
        r"(.*?)</text>",
        re.DOTALL,
    )

    # Group spans by line number
    line_map: dict[int, list[dict[str, Any]]] = {}

    for match in text_pattern.finditer(svg_text):
        rule_id = f"r{match.group(1)}"
        x = float(match.group(2))
        y = float(match.group(3))
        width = float(match.group(4))
        line_num = int(match.group(5))
        raw_text = match.group(6)

        # Decode HTML entities (&#160; -> space, etc.)
        text = html.unescape(raw_text)

        # Skip empty/whitespace-only spans at line edges (padding)
        if not text.strip():
            continue

        # Get style info
        style = styles.get(rule_id, {})
        color = style.get("fill", "unknown")
        bold = "bold" in style.get("font-weight", "")
        italic = "italic" in style.get("font-style", "")

        span = {
            "text": text,
            "x": x,
            "width": width,
            "class": rule_id,
            "color": color,
            "bold": bold,
            "italic": italic,
        }

        if line_num not in line_map:
            line_map[line_num] = []
        line_map[line_num].append(span)

    # Sort lines and spans within lines
    lines = []
    for line_num in sorted(line_map.keys()):
        spans = sorted(line_map[line_num], key=lambda s: s["x"])

        # Calculate line Y from first span
        y = 0.0
        for match in text_pattern.finditer(svg_text):
            if int(match.group(5)) == line_num:
                y = float(match.group(3))
                break

        # Merge text for the full line content
        full_text = "".join(s["text"] for s in spans)

        lines.append(
            {
                "line_num": line_num,
                "y": y,
                "full_text": full_text,
                "spans": spans,
            }
        )

    return lines


def _classify_layout(
    lines: list[dict[str, Any]], dims: dict[str, float]
) -> dict[str, Any]:
    """Classify lines into layout regions based on position and content."""
    height = dims.get("height", 1)

    regions: dict[str, list[int]] = {
        "header": [],
        "content": [],
        "input_area": [],
        "status_bar": [],
    }

    for line in lines:
        rel_y = line["y"] / height if height > 0 else 0
        ln = line["line_num"]

        if rel_y < 0.06:
            regions["header"].append(ln)
        elif rel_y > 0.92:
            regions["status_bar"].append(ln)
        elif rel_y > 0.82:
            regions["input_area"].append(ln)
        else:
            regions["content"].append(ln)

    # Detect message types in content region
    messages = _detect_messages(lines, regions.get("content", []))

    return {
        "regions": {k: {"lines": v, "count": len(v)} for k, v in regions.items()},
        "messages": messages,
    }


def _detect_messages(
    lines: list[dict[str, Any]], content_line_nums: list[int]
) -> list[dict[str, Any]]:
    """Detect chat message blocks within the content region.

    Identifies user messages, assistant messages, thinking blocks,
    and tool use blocks by examining text content and styling.
    """
    messages = []
    line_lookup = {ln["line_num"]: ln for ln in lines}

    current_msg: dict[str, Any] | None = None

    for ln_num in content_line_nums:
        line = line_lookup.get(ln_num)
        if not line:
            continue

        full = line["full_text"].strip()
        if not full:
            continue

        # Detect message type transitions
        msg_type = _classify_line(line)

        if msg_type and msg_type != (current_msg or {}).get("type"):
            # Save previous message
            if current_msg:
                messages.append(current_msg)

            current_msg = {
                "type": msg_type,
                "start_line": ln_num,
                "end_line": ln_num,
                "text_lines": [full],
            }
        elif current_msg:
            current_msg["end_line"] = ln_num
            current_msg["text_lines"].append(full)

    if current_msg:
        messages.append(current_msg)

    return messages


def _classify_line(line: dict[str, Any]) -> str | None:
    """Classify a line as belonging to a message type.

    Returns: "user", "thinking", "tool", "assistant", or None
    """
    full = line["full_text"].strip()
    spans = line.get("spans", [])

    if not full:
        return None

    # User messages: typically have a distinct accent color (orange/gold)
    # and are plain text without markdown formatting
    # Check for user message indicators
    for span in spans:
        # Thinking blocks: italic text, collapsible with "Thinking:" prefix
        if "Thinking:" in span["text"] and span.get("italic"):
            return "thinking"

        # Tool blocks: "Tool:" prefix
        if "Tool:" in span["text"]:
            return "tool"

    # Check if any span has bold + specific accent color (user message indicator)
    first_meaningful = next(
        (s for s in spans if s["text"].strip() and len(s["text"].strip()) > 1),
        None,
    )

    if first_meaningful:
        color = first_meaningful.get("color", "").lower()
        # Orange/gold colors typically indicate user messages
        if color in ("#cb7700", "#ff9900", "#cc7700"):
            return "user"

        # Blue/cyan colors typically indicate assistant messages
        if color.startswith("#55") or color.startswith("#59"):
            return "assistant"

    # Check for markdown-rendered content (bold headers, code highlighting)
    has_bold = any(s.get("bold") for s in spans)
    has_code_color = any(
        s.get("color", "").lower() in ("#bcbc51", "#b5bd68") for s in spans
    )
    if has_bold or has_code_color:
        return "assistant"

    return None


def to_yaml_dict(parsed: dict[str, Any], source: str = "") -> dict[str, Any]:
    """Convert parsed SVG data to a clean YAML-friendly dict.

    This is the primary output format for the UX testing pipeline.
    """
    layout = parsed["layout"]
    lines = parsed["lines"]
    theme = parsed["theme"]

    # Simplify lines for YAML output — show text and key metadata
    simplified_lines = []
    for line in lines:
        if not line["full_text"].strip():
            continue
        entry: dict[str, Any] = {
            "line": line["line_num"],
            "text": line["full_text"],
        }
        # Note styling if interesting
        has_bold = any(s.get("bold") for s in line["spans"])
        has_italic = any(s.get("italic") for s in line["spans"])
        colors = list({s["color"] for s in line["spans"] if s["color"] != "unknown"})

        if has_bold:
            entry["bold"] = True
        if has_italic:
            entry["italic"] = True
        if len(colors) > 1:
            entry["colors"] = colors

        simplified_lines.append(entry)

    return {
        "tui_svg_analysis": {
            "source": source or "unknown",
            "dimensions": parsed["dimensions"],
            "theme": theme,
            "layout": {
                "regions": {k: v["count"] for k, v in layout["regions"].items()},
                "messages": [
                    {
                        "type": m["type"],
                        "lines": f"{m['start_line']}-{m['end_line']}",
                        "preview": m["text_lines"][0][:80],
                    }
                    for m in layout.get("messages", [])
                ],
            },
            "content": simplified_lines,
        }
    }


def _build_theme(
    lines: list[dict[str, Any]], styles: dict[str, dict[str, str]]
) -> dict[str, Any]:
    """Summarize color usage across all text spans."""
    color_counts: dict[str, int] = {}
    for line in lines:
        for span in line.get("spans", []):
            color = span.get("color", "unknown")
            if color != "unknown":
                color_counts[color] = color_counts.get(color, 0) + 1

    # Sort by frequency
    sorted_colors = sorted(color_counts.items(), key=lambda x: -x[1])

    theme = {}
    role_names = [
        "primary_text",
        "secondary_text",
        "accent_1",
        "accent_2",
        "accent_3",
        "muted",
    ]
    for i, (color, count) in enumerate(sorted_colors[: len(role_names)]):
        theme[role_names[i]] = {"hex": color, "span_count": count}

    return theme


if __name__ == "__main__":
    import sys

    import yaml

    if len(sys.argv) < 2:
        print("Usage: python svg_parser.py <svg_file>", file=sys.stderr)
        sys.exit(1)

    result = parse_tui_svg(sys.argv[1])
    yaml_dict = to_yaml_dict(result, source=Path(sys.argv[1]).name)
    print(yaml.dump(yaml_dict, default_flow_style=False, sort_keys=False))
