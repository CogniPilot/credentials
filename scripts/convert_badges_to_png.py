#!/usr/bin/env python3
"""
Convert SVG badge images to PNG for social sharing.

LinkedIn and other social platforms need PNG images for og:image tags.
Uses cairosvg (pure Python, no external dependencies like inkscape).
"""

import sys
from pathlib import Path

try:
    import cairosvg
except ImportError:
    print("Error: cairosvg is required. Install with: pip install cairosvg")
    sys.exit(1)


def convert_svg_to_png(svg_path: Path, png_path: Path, width: int = 400):
    """Convert an SVG file to PNG using cairosvg."""
    cairosvg.svg2png(
        url=str(svg_path),
        write_to=str(png_path),
        output_width=width,
        output_height=width
    )


def main():
    # Find all SVG badges
    script_dir = Path(__file__).parent
    repo_root = script_dir.parent
    badges_dir = repo_root / 'docs' / 'images' / 'badges'

    svg_files = list(badges_dir.glob('*.svg'))

    if not svg_files:
        print("No SVG files found")
        return

    print(f"Converting {len(svg_files)} SVG files to PNG...")

    for svg_path in svg_files:
        png_path = svg_path.with_suffix('.png')
        try:
            convert_svg_to_png(svg_path, png_path)
            print(f"Converted: {svg_path.name} -> {png_path.name}")
        except Exception as e:
            print(f"Error converting {svg_path.name}: {e}")

    print("Done!")


if __name__ == '__main__':
    main()
