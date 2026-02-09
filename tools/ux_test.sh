#!/usr/bin/env bash
# UX test pipeline: capture TUI -> SVG parse (text) + image analyze (layout) -> YAML
#
# The SVG parser extracts exact text content, colors, and styles.
# The image analyzer adds layout/brightness data from the rasterized PNG.
# Together they give a complete picture for UX debugging.
#
# Usage:
#   ./tools/ux_test.sh                    # Empty app state
#   ./tools/ux_test.sh --mock-chat        # With sample chat content
#   ./tools/ux_test.sh --svg-only         # Skip image analysis (fastest)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV="$PROJECT_DIR/.venv/bin/python"
OUTPUT_DIR="$PROJECT_DIR/.ux-tests"

mkdir -p "$OUTPUT_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
PNG="$OUTPUT_DIR/capture_${TIMESTAMP}.png"
SVG="$OUTPUT_DIR/capture_${TIMESTAMP}.svg"
SVG_YAML="$OUTPUT_DIR/svg_analysis_${TIMESTAMP}.yaml"
IMG_YAML="$OUTPUT_DIR/img_analysis_${TIMESTAMP}.yaml"

# Parse flags
CAPTURE_ARGS="--svg"  # Always capture SVG
SVG_ONLY=false
for arg in "$@"; do
    case "$arg" in
        --mock-chat|--width=*|--height=*)
            CAPTURE_ARGS="$CAPTURE_ARGS $arg"
            ;;
        --svg-only)
            SVG_ONLY=true
            ;;
    esac
done

echo "=== Step 1: Capture TUI screenshot ==="
$VENV "$SCRIPT_DIR/tui_capture.py" -o "$PNG" $CAPTURE_ARGS

echo ""
echo "=== Step 2: Parse SVG (text + styling) ==="
$VENV "$SCRIPT_DIR/svg_parser.py" "$SVG" > "$SVG_YAML"
echo "SVG analysis saved: $SVG_YAML"

if [ "$SVG_ONLY" = false ]; then
    echo ""
    echo "=== Step 3: Analyze image (layout + colors) ==="
    $VENV "$SCRIPT_DIR/tui_analyze.py" "$PNG" -o "$IMG_YAML" 2>&1
fi

echo ""
echo "=== Results ==="
echo "Screenshot PNG: $PNG"
echo "Screenshot SVG: $SVG"
echo "SVG analysis:   $SVG_YAML  (text content, colors, message detection)"
if [ "$SVG_ONLY" = false ]; then
    echo "Image analysis: $IMG_YAML  (layout bands, color palette, sidebar)"
fi
echo ""
echo "--- SVG Analysis (primary) ---"
cat "$SVG_YAML"
