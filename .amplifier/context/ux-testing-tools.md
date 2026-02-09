# TUI UX Testing Tools

## Overview

The `tools/` directory contains a headless UX testing pipeline for the Amplifier TUI.
It captures screenshots without a terminal, extracts structured data, and outputs YAML
that can be used for iterative UX debugging without relying on LLM image recognition.

**Key insight**: Textual exports SVG with exact text content, positions, colors, and styles.
Parsing the SVG directly is far superior to OCR for TUI analysis — pixel-perfect text
extraction with zero ML overhead.

## Pipeline Architecture

```
Textual App (headless via Pilot)
        |
        v
   SVG + PNG export (tui_capture.py)
        |
        +---> SVG parser (svg_parser.py) --> text content, colors, styles, message detection
        |
        +---> Image analyzer (tui_analyze.py) --> layout bands, color palette, sidebar detection
        |
        v
   Structured YAML (primary artifact for debugging)
```

## Tools

### tui_capture.py — Screenshot Capture

Runs the TUI app headlessly using Textual's Pilot framework and exports SVG + PNG.

```bash
# Empty app state
.venv/bin/python tools/tui_capture.py -o capture.png --svg

# With mock chat content (user messages, thinking, tools, assistant markdown)
.venv/bin/python tools/tui_capture.py -o capture.png --mock-chat --svg

# Custom terminal size
.venv/bin/python tools/tui_capture.py -o capture.png --width 160 --height 60 --svg
```

**Mock content includes**: user message, collapsed thinking block, tool call block,
assistant markdown with code blocks, second user message, expanded thinking block,
second assistant response. This covers all widget types for rendering validation.

**Dependencies**: cairosvg (for SVG->PNG), textual (already in project venv)

### svg_parser.py — Text Extraction (PRIMARY)

Parses the SVG to extract exact text content, colors, bold/italic styling, and line positions.
This is the primary analysis tool because it gives pixel-perfect text with zero uncertainty.

```bash
.venv/bin/python tools/svg_parser.py capture.svg
```

**Output includes**:
- `theme`: Color usage frequency (primary_text, secondary_text, accents)
- `layout.regions`: Line counts per region (header, content, input_area, status_bar)
- `layout.messages`: Detected message blocks with type (user/thinking/tool/assistant)
- `content`: Every text line with content, colors, bold/italic flags

**Message detection heuristics**:
- User messages: orange/gold color (#cb7700)
- Thinking blocks: italic text with "Thinking:" prefix
- Tool blocks: "Tool:" prefix
- Assistant messages: blue (#5599dd) with markdown formatting (bold, code highlighting)

**Dependencies**: None beyond stdlib (xml, re, html) + pyyaml

### tui_analyze.py — Image Analysis (SUPPLEMENTARY)

Analyzes the rasterized PNG for layout structure that's harder to get from SVG alone.

```bash
# Lite backend (Pillow only, fast)
.venv/bin/python tools/tui_analyze.py capture.png

# Full backend (requires amplifier-ux-analyzer venv with opencv + sklearn)
.venv/bin/python tools/tui_analyze.py capture.png --backend full
```

**Lite backend output**:
- Color palette (quantized top 8 colors with frequencies)
- Layout bands (row brightness analysis -> header/content/input/status_bar)
- Sidebar detection (vertical brightness discontinuity)
- Brightness distribution summary

**Full backend** (when amplifier-ux-analyzer deps are installed):
- Everything from lite + contour-based element detection + OCR text extraction
- Runs in the amplifier-ux-analyzer venv (separate from TUI venv)

**Dependencies**: Pillow (lite), opencv-python-headless + scikit-learn (full)

### ux_test.sh — Combined Pipeline

One command to capture + analyze + show results.

```bash
# Empty app
./tools/ux_test.sh

# With mock content
./tools/ux_test.sh --mock-chat

# SVG analysis only (fastest)
./tools/ux_test.sh --mock-chat --svg-only
```

**Output files** go to `.ux-tests/` (gitignored) with timestamps.

## UX Debugging Workflow

### 1. Capture baseline
```bash
./tools/ux_test.sh --mock-chat
```

### 2. Read the SVG YAML
The SVG analysis is the primary artifact. Look for:
- **Message detection**: Are all message types (user/thinking/tool/assistant) detected?
- **Text content**: Is the rendered text what you expect?
- **Styling**: Are bold/italic/colors correct for each message type?
- **Layout regions**: Are lines in the right regions (header/content/input/status)?

### 3. Make changes to the TUI code

### 4. Re-capture and diff
```bash
./tools/ux_test.sh --mock-chat
# Compare YAML files to verify changes
diff .ux-tests/svg_analysis_BEFORE.yaml .ux-tests/svg_analysis_AFTER.yaml
```

### 5. Iterate

## Adding New Mock Content

To test new widget types or edge cases, edit `_inject_mock_content()` in
`tools/tui_capture.py`. It uses the actual TUI widget classes (UserMessage,
AssistantMessage, Collapsible) so screenshots reflect real rendering.

## Extending the SVG Parser

The message detection in `svg_parser.py` uses color and text-prefix heuristics.
If TUI styling changes, update `_classify_line()` with new color values or
text patterns.

## amplifier-ux-analyzer Integration

The project at `~/dev/ANext/amplifier-ux-analyzer` provides a more advanced
image analysis toolkit with opencv contour detection and sklearn color clustering.
It's designed for browser UX but the core analyzer works on any image.

**Setup** (one-time, requires large package downloads):
```bash
cd ~/dev/ANext/amplifier-ux-analyzer
uv venv venv
uv pip install --python venv/bin/python opencv-python-headless numpy scikit-learn pillow pyyaml
```

Then use `--backend full` with tui_analyze.py.

For TUI work, the SVG parser is usually sufficient and much faster.
The full analyzer adds value when you need pixel-level layout analysis
that goes beyond what SVG parsing provides.
