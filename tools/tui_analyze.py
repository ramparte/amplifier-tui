"""Analyze a TUI screenshot and produce structured YAML.

Two backends:
  1. "lite" (default) - Uses only Pillow. No opencv/sklearn needed.
     Extracts colors, text-region heuristics, and basic layout.
  2. "full" - Uses amplifier-ux-analyzer (opencv + sklearn + easyocr).
     Adds contour-based element detection and OCR text extraction.

The lite backend is sufficient for TUI work because terminal UIs have
predictable grid layouts. The full backend adds value when you need
actual OCR text extraction from pixel data.

Usage:
    python tools/tui_analyze.py tui_capture.png              # lite (fast)
    python tools/tui_analyze.py tui_capture.png --backend full  # full analyzer
    python tools/tui_analyze.py tui_capture.png -o out.yaml  # save to file
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

UX_ANALYZER_ROOT = Path(__file__).parent.parent.parent / "amplifier-ux-analyzer"
UX_ANALYZER_PYTHON = UX_ANALYZER_ROOT / "venv" / "bin" / "python"


# ── Lite backend (Pillow only) ───────────────────────────────────────


def analyze_lite(image_path: str) -> dict[str, Any]:
    """Analyze screenshot using only Pillow. Fast, no heavy deps."""
    from PIL import Image

    img = Image.open(image_path).convert("RGB")
    width, height = img.size
    pixels = (
        list(img.get_flattened_data())
        if hasattr(img, "get_flattened_data")
        else list(img.getdata())
    )

    # --- Color palette (top N by frequency) ---
    # Quantize to reduce unique colors, then count
    quantized = img.quantize(colors=16, method=Image.Quantize.MEDIANCUT)
    palette_data = quantized.getpalette()
    q_pixels = list(quantized.getdata())
    color_counts: Counter[int] = Counter(q_pixels)
    total = len(q_pixels)

    colors = []
    for idx, count in color_counts.most_common(8):
        r, g, b = palette_data[idx * 3 : idx * 3 + 3]
        colors.append(
            {
                "hex": f"#{r:02x}{g:02x}{b:02x}",
                "rgb": [r, g, b],
                "frequency": round(count / total, 4),
            }
        )

    # --- Row-by-row brightness to detect layout bands ---
    # TUI layout: header (bright/colored), content (mixed), footer (bright/colored)
    row_brightness = []
    for y in range(height):
        row_pixels = pixels[y * width : (y + 1) * width]
        avg_bright = sum(
            (0.299 * r + 0.587 * g + 0.114 * b) for r, g, b in row_pixels
        ) / max(width, 1)
        row_brightness.append(avg_bright)

    # Detect non-background bands (rows significantly brighter than median)
    if row_brightness:
        median_bright = sorted(row_brightness)[len(row_brightness) // 2]
    else:
        median_bright = 0

    # Find regions where brightness differs from background
    threshold = median_bright + 15  # slightly above median = has content
    regions = _detect_bands(row_brightness, threshold, height, width)

    # --- Horizontal structure (sidebar detection) ---
    # Sample middle rows, look for vertical brightness change (sidebar border)
    sidebar = _detect_sidebar(img, width, height)

    return {
        "metadata": {"dimensions": {"width": width, "height": height}},
        "colors": colors,
        "regions": regions,
        "sidebar": sidebar,
        "row_brightness_summary": {
            "min": round(min(row_brightness), 1) if row_brightness else 0,
            "max": round(max(row_brightness), 1) if row_brightness else 0,
            "median": round(median_bright, 1),
        },
    }


def _detect_bands(
    row_brightness: list[float], threshold: float, height: int, width: int
) -> list[dict]:
    """Detect horizontal layout bands from row brightness."""
    bands = []
    in_band = False
    band_start = 0

    for y, bright in enumerate(row_brightness):
        if bright > threshold and not in_band:
            in_band = True
            band_start = y
        elif bright <= threshold and in_band:
            in_band = False
            bands.append({"y_start": band_start, "y_end": y, "height": y - band_start})

    if in_band:
        bands.append(
            {
                "y_start": band_start,
                "y_end": height,
                "height": height - band_start,
            }
        )

    # Classify bands by position
    regions = []
    for band in bands:
        y_center = (band["y_start"] + band["y_end"]) / 2
        rel_y = y_center / height
        if rel_y < 0.08:
            rtype = "header"
        elif rel_y > 0.92:
            rtype = "status_bar"
        elif rel_y > 0.80:
            rtype = "input_area"
        else:
            rtype = "content"

        regions.append(
            {
                "type": rtype,
                "bounds": {
                    "x": 0,
                    "y": band["y_start"],
                    "width": width,
                    "height": band["height"],
                },
                "relative_position": round(rel_y, 3),
            }
        )

    return regions


def _detect_sidebar(img, width: int, height: int) -> dict | None:
    """Detect sidebar by looking for vertical brightness discontinuity."""
    # Sample the middle third of the image vertically
    y_start = height // 3
    y_end = 2 * height // 3
    crop = img.crop((0, y_start, width, y_end))
    pixels = list(crop.getdata())
    crop_h = y_end - y_start

    # Average brightness per column
    col_brightness = []
    for x in range(width):
        col_pixels = [pixels[y * width + x] for y in range(crop_h)]
        avg = sum(0.299 * r + 0.587 * g + 0.114 * b for r, g, b in col_pixels) / max(
            crop_h, 1
        )
        col_brightness.append(avg)

    # Look for a sharp brightness jump (sidebar border)
    # Check left third of image for a divider
    search_range = width // 3
    max_diff = 0
    best_x = None
    for x in range(5, search_range):
        left_avg = sum(col_brightness[x - 3 : x]) / 3
        right_avg = sum(col_brightness[x : x + 3]) / 3
        diff = abs(right_avg - left_avg)
        if diff > max_diff:
            max_diff = diff
            best_x = x

    if best_x and max_diff > 10:
        return {
            "detected": True,
            "x_position": best_x,
            "width_fraction": round(best_x / width, 3),
            "confidence": round(min(max_diff / 50, 1.0), 3),
        }
    return {"detected": False}


# ── Full backend (amplifier-ux-analyzer) ─────────────────────────────


def analyze_full(image_path: str) -> dict[str, Any]:
    """Run the full ux-analyzer. Requires opencv + sklearn in analyzer venv."""
    script = f"""
import sys, json
sys.path.insert(0, {str(UX_ANALYZER_ROOT)!r})
from amplifier_ux_analyzer.core.analyzer import UXAnalyzer
analyzer = UXAnalyzer({image_path!r}, use_ocr=True)
result = analyzer.analyze()
print(json.dumps(result))
"""
    result = subprocess.run(
        [str(UX_ANALYZER_PYTHON), "-c", script],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        print(f"Analyzer stderr:\n{result.stderr}", file=sys.stderr)
        raise RuntimeError(f"Analyzer failed: {result.returncode}")

    lines = [ln for ln in result.stdout.strip().splitlines() if ln.strip()]
    return json.loads(lines[-1])


# ── Format for YAML output ───────────────────────────────────────────


def to_tui_yaml(raw: dict[str, Any], image_path: str, backend: str) -> dict:
    """Build the YAML structure from analyzer output."""
    dims = raw.get("metadata", {}).get("dimensions", {})
    colors = raw.get("colors", [])
    regions = raw.get("regions", [])
    sidebar = raw.get("sidebar")

    # Color theme — name by frequency rank
    theme = {}
    role_names = [
        "background",
        "secondary_bg",
        "border",
        "text",
        "accent_1",
        "accent_2",
    ]
    for i, c in enumerate(colors[: len(role_names)]):
        theme[role_names[i]] = {
            "hex": c["hex"],
            "frequency": c["frequency"],
        }

    # Region summary
    layout_regions = []
    for r in regions:
        entry = {"type": r["type"], "bounds": r["bounds"]}
        if "relative_position" in r:
            entry["rel_y"] = r["relative_position"]
        layout_regions.append(entry)

    # Text elements (full backend only)
    text_section = None
    if "text_elements" in raw:
        height = dims.get("height", 1)
        header_texts, content_texts, footer_texts = [], [], []
        for t in raw["text_elements"]:
            y_center = t["bounds"]["y"] + t["bounds"]["height"] / 2
            rel_y = y_center / height
            entry = {
                "text": t["text"],
                "confidence": round(t["confidence"], 3),
            }
            if rel_y < 0.15:
                header_texts.append(entry)
            elif rel_y > 0.85:
                footer_texts.append(entry)
            else:
                content_texts.append(entry)
        text_section = {
            "header": header_texts,
            "content": content_texts,
            "footer": footer_texts,
            "total": len(raw["text_elements"]),
        }

    result = {
        "tui_analysis": {
            "source": Path(image_path).name,
            "backend": backend,
            "dimensions": dims,
            "theme": theme,
            "layout": {
                "regions": layout_regions,
                "sidebar": sidebar,
            },
        }
    }

    if text_section:
        result["tui_analysis"]["text"] = text_section

    # Brightness summary (lite backend)
    if "row_brightness_summary" in raw:
        result["tui_analysis"]["brightness"] = raw["row_brightness_summary"]

    return result


def main():
    parser = argparse.ArgumentParser(description="Analyze TUI screenshot to YAML")
    parser.add_argument("image", help="Path to PNG screenshot")
    parser.add_argument("-o", "--output", help="Output YAML path (default: stdout)")
    parser.add_argument(
        "--backend",
        choices=["lite", "full"],
        default="lite",
        help="Analysis backend (default: lite)",
    )
    parser.add_argument(
        "--raw-json",
        action="store_true",
        help="Also dump raw JSON",
    )
    args = parser.parse_args()

    if not Path(args.image).exists():
        print(f"Error: {args.image} not found", file=sys.stderr)
        sys.exit(1)

    print(f"Analyzing {args.image} (backend={args.backend})...", file=sys.stderr)

    if args.backend == "full":
        raw = analyze_full(args.image)
    else:
        raw = analyze_lite(args.image)

    if args.raw_json:
        json_path = Path(args.image).with_suffix(".json")
        json_path.write_text(json.dumps(raw, indent=2))
        print(f"Raw JSON: {json_path}", file=sys.stderr)

    tui_yaml = to_tui_yaml(raw, args.image, args.backend)
    yaml_str = yaml.dump(tui_yaml, default_flow_style=False, sort_keys=False)

    if args.output:
        Path(args.output).write_text(yaml_str)
        print(f"YAML saved: {args.output}", file=sys.stderr)
    else:
        print(yaml_str)


if __name__ == "__main__":
    main()
