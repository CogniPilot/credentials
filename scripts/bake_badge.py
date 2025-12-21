#!/usr/bin/env python3
"""
Bake an OpenBadges 3.0 credential into an SVG image.

Per the OpenBadges 3.0 specification, baking embeds the credential JSON
into the SVG so that badge-aware software can extract and verify it.

For SVG, the credential is embedded in an <openbadges:credential> element
within the SVG's metadata.

This module also supports:
- Adding earner names to badge SVGs
- Converting baked SVGs to PNG format
"""

import argparse
import base64
import json
import re
import sys
from pathlib import Path

try:
    import cairosvg
    HAS_CAIROSVG = True
except ImportError:
    HAS_CAIROSVG = False


# OpenBadges namespace for SVG
OPENBADGES_NS = "https://purl.imsglobal.org/ob/v3p0"


def _text_to_svg_path(text: str, font_size: float, center_x: float, baseline_y: float,
                      font_family: str = "Open Sans") -> str:
    """
    Convert text to an SVG path using Cairo.

    This ensures identical rendering in both SVG and PNG by converting
    text to vector paths rather than relying on font rendering.

    Args:
        text: The text to convert
        font_size: Font size in SVG units
        center_x: X coordinate for center of text
        baseline_y: Y coordinate for text baseline
        font_family: Font family to use (default "Open Sans")

    Returns:
        SVG path element as a string
    """
    import cairo

    # Use higher resolution by scaling up, then scale path coordinates back down
    # This gives us more precise curves from the font rendering
    scale_factor = 10.0
    scaled_font_size = font_size * scale_factor
    scaled_center_x = center_x * scale_factor
    scaled_baseline_y = baseline_y * scale_factor

    # Create a recording surface to capture the path
    surface = cairo.RecordingSurface(cairo.CONTENT_ALPHA, None)
    ctx = cairo.Context(surface)

    # Set up font - use Open Sans Bold
    ctx.select_font_face(font_family, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(scaled_font_size)

    # Get text extents for centering
    extents = ctx.text_extents(text)
    text_width = extents.width

    # Calculate starting x position to center text
    start_x = scaled_center_x - text_width / 2

    # Move to starting position and create text path
    ctx.move_to(start_x, scaled_baseline_y)
    ctx.text_path(text)

    # Extract path data with high precision, scaling back down
    path_data = []
    for item in ctx.copy_path():
        if item[0] == cairo.PATH_MOVE_TO:
            x, y = item[1][0] / scale_factor, item[1][1] / scale_factor
            path_data.append(f"M {x:.6f},{y:.6f}")
        elif item[0] == cairo.PATH_LINE_TO:
            x, y = item[1][0] / scale_factor, item[1][1] / scale_factor
            path_data.append(f"L {x:.6f},{y:.6f}")
        elif item[0] == cairo.PATH_CURVE_TO:
            x1, y1 = item[1][0] / scale_factor, item[1][1] / scale_factor
            x2, y2 = item[1][2] / scale_factor, item[1][3] / scale_factor
            x3, y3 = item[1][4] / scale_factor, item[1][5] / scale_factor
            path_data.append(
                f"C {x1:.6f},{y1:.6f} "
                f"{x2:.6f},{y2:.6f} "
                f"{x3:.6f},{y3:.6f}"
            )
        elif item[0] == cairo.PATH_CLOSE_PATH:
            path_data.append("Z")

    return " ".join(path_data)


def add_earner_name(svg_content: str, earner_name: str,
                    max_font_size: float = 3.0,
                    min_font_size: float = 1.2,
                    font_family: str = "Open Sans") -> str:
    """
    Add the earner's name to an SVG badge with auto-sizing.

    The name is centered horizontally and placed below the COGNIPILOT text
    within the inner dark circle of the badge. Font size automatically
    adjusts based on name length, and long names wrap to multiple lines.

    Text is converted to SVG paths to ensure identical rendering in both
    SVG and PNG formats.

    Text positioning follows the curved inner boundary of the red ring,
    using 4 horizontal zones with decreasing widths as y increases.

    Args:
        svg_content: The SVG content as a string
        earner_name: The name to add to the badge
        max_font_size: Maximum font size (default 3.0)
        min_font_size: Minimum font size (default 1.2)
        font_family: Font family to use (default "sans-serif")

    Returns:
        The modified SVG content with the earner name added
    """
    import math
    import cairo

    # Circle parameters: inner dark circle centered at (40, 40) with radius 25
    # Use a smaller effective radius to ensure text stays well within the boundary
    center_x = 40
    center_y = 40
    inner_radius = 23  # Slightly reduced from 25 to provide margin from the red ring

    # Define the 4 text zones (y ranges and their max widths based on circle curve)
    # Zones are positioned below COGNIPILOT with a gap
    # Each zone is 3 units tall
    zones = [
        {'y_top': 51.5, 'y_bottom': 54.5},  # Zone 1
        {'y_top': 54.5, 'y_bottom': 57.5},  # Zone 2
        {'y_top': 57.5, 'y_bottom': 60.5},  # Zone 3
        {'y_top': 60.5, 'y_bottom': 63.5},  # Zone 4
    ]

    # Calculate max width for each zone based on circle geometry
    for zone in zones:
        y_mid = (zone['y_top'] + zone['y_bottom']) / 2
        dy = y_mid - center_y
        if abs(dy) < inner_radius:
            half_width = math.sqrt(inner_radius**2 - dy**2)
            zone['max_width'] = half_width * 2
        else:
            zone['max_width'] = 0

    # Create a Cairo context for text measurement
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)
    ctx = cairo.Context(surface)

    def measure_text_width(text, fsize):
        """Measure text width using Cairo (actual path width)."""
        ctx.select_font_face(font_family, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        ctx.set_font_size(fsize)
        extents = ctx.text_extents(text)
        return extents.width

    def split_for_zones(text, fsize, zone_widths):
        """Split text into lines that fit within decreasing zone widths."""
        words = text.split()
        result_lines = []
        current_line = []
        zone_idx = 0

        for word in words:
            # Get max width for current zone (use last zone width if we exceed zones)
            max_w = zone_widths[min(zone_idx, len(zone_widths) - 1)]

            test_line = current_line + [word]
            test_text = ' '.join(test_line)
            test_width = measure_text_width(test_text, fsize)

            if test_width <= max_w:
                current_line.append(word)
            else:
                if current_line:
                    result_lines.append(' '.join(current_line))
                    zone_idx += 1
                current_line = [word]

        if current_line:
            result_lines.append(' '.join(current_line))

        return result_lines

    # Get zone widths (only use first 3 zones for up to 3 lines)
    max_lines = 3
    zone_widths = [z['max_width'] for z in zones[:max_lines]]

    def lines_fit(ls, fsize, widths):
        """Check if all lines fit within their respective zone widths."""
        if len(ls) > max_lines:
            return False
        for i, line in enumerate(ls):
            w = widths[min(i, len(widths) - 1)]
            if measure_text_width(line, fsize) > w:
                return False
        return True

    # Strategy: Try to fit at max font size first, then allow wrapping up to 3 lines
    # Only reduce font size if wrapping to 3 lines isn't enough
    font_size = max_font_size
    lines = [earner_name]

    # Check if single line fits at max font size
    if measure_text_width(earner_name, font_size) <= zone_widths[0]:
        # Single line fits at max font size
        pass
    else:
        # Try wrapping to multiple lines at max font size first
        lines = split_for_zones(earner_name, font_size, zone_widths)

        if not lines_fit(lines, font_size, zone_widths):
            # Wrapping at max font size doesn't work, try reducing font
            # but prioritize keeping font size high with more lines
            found_fit = False

            # Try each font size from max down to min
            for test_size in [max_font_size - 0.1 * i for i in range(int((max_font_size - min_font_size) / 0.1) + 1)]:
                if test_size < min_font_size:
                    test_size = min_font_size

                # At this font size, try wrapping
                test_lines = split_for_zones(earner_name, test_size, zone_widths)

                if lines_fit(test_lines, test_size, zone_widths):
                    font_size = test_size
                    lines = test_lines
                    found_fit = True
                    break

            # If still no fit at min_font_size, keep reducing below min
            if not found_fit:
                font_size = min_font_size
                while font_size > 0.8:
                    font_size -= 0.1
                    lines = split_for_zones(earner_name, font_size, zone_widths)
                    if lines_fit(lines, font_size, zone_widths):
                        break

    # Calculate total text area height
    line_height = font_size * 1.4
    num_lines = len(lines)
    total_text_height = line_height * num_lines

    # Calculate available vertical space (zones 1-4, but limit to zones used)
    zones_needed = min(num_lines, len(zones))
    area_y_top = zones[0]['y_top']
    area_y_bottom = zones[zones_needed - 1]['y_bottom']
    available_height = area_y_bottom - area_y_top

    # Center text block vertically within the used zones
    vertical_padding = (available_height - total_text_height) / 2
    start_y = area_y_top + vertical_padding + line_height * 0.8  # 0.8 adjusts for baseline

    # The text group is inserted inside layer1, which has transform="translate(-34.910359,-34.910361)"
    # Inside layer1, circles are at cx=74.910362, cy=74.910362
    # So text at x=74.9 will be centered on the circle
    # Y positions need the offset added
    layer1_offset = 34.910361
    layer1_center_x = 74.910362

    # Convert each line to an SVG path
    path_elements = []
    for i, line in enumerate(lines):
        y = start_y + (i * line_height) + layer1_offset
        path_d = _text_to_svg_path(line, font_size, layer1_center_x, y, font_family)
        if path_d:
            path_elements.append(f'    <path d="{path_d}" style="fill:#ffffff"/>')

    path_content = '\n'.join(path_elements)

    name_element = f'''  <g
     aria-label="{earner_name}"
     id="earner-name">
{path_content}
  </g>
'''

    # Check if there's already an earner name and replace it
    if 'id="earner-name"' in svg_content:
        svg_content = re.sub(
            r'<g[^>]*id="earner-name"[^>]*>.*?</g>\s*',
            name_element,
            svg_content,
            flags=re.DOTALL
        )
    else:
        # Insert inside layer1 group, before the closing </g></g></svg> or </g></svg>
        # This ensures the text is part of the main layer and rendered correctly
        if '</g></g></svg>' in svg_content:
            svg_content = svg_content.replace(
                '</g></g></svg>',
                f'{name_element}</g></g></svg>'
            )
        elif '</g></svg>' in svg_content:
            svg_content = svg_content.replace(
                '</g></svg>',
                f'{name_element}</g></svg>'
            )
        else:
            # Fallback: insert before </svg>
            svg_content = re.sub(
                r'(</svg>)',
                f'{name_element}\\1',
                svg_content
            )

    return svg_content


def bake_png(image: 'Image', credential_url: str) -> 'Image':
    """
    Bake a credential URL into a PNG image's metadata.

    Per OpenBadges 3.0 specification, the credential is referenced via a URL
    stored in a PNG tEXt chunk with the keyword 'openbadges'.

    Args:
        image: PIL Image object
        credential_url: URL to the credential JSON

    Returns:
        PIL Image with credential metadata baked in
    """
    from PIL import PngImagePlugin

    # Create metadata with openbadges key
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("openbadges", credential_url)

    # Store metadata in image info for later saving
    image.info['pnginfo'] = metadata
    image.info['openbadges'] = credential_url

    return image


def extract_credential_from_png(png_path: Path) -> str | None:
    """
    Extract the credential URL from a baked PNG image.

    Args:
        png_path: Path to the PNG file

    Returns:
        The credential URL, or None if not found
    """
    from PIL import Image

    img = Image.open(png_path)

    # Check text chunks
    if hasattr(img, 'text') and 'openbadges' in img.text:
        return img.text['openbadges']

    # Check info dict
    if 'openbadges' in img.info:
        return img.info['openbadges']

    return None


def svg_to_png(svg_content: str, output_path: Path, width: int = 500,
               linkedin_optimized: bool = True,
               credential_url: str = None) -> None:
    """
    Convert SVG content to PNG, optionally baking in a credential URL.

    Args:
        svg_content: The SVG content as a string
        output_path: Path to save the PNG file
        width: Width of the output PNG in pixels (default 500)
        linkedin_optimized: If True, creates a 1200x627 image with badge centered
                           on transparent background for optimal LinkedIn display (default True)
        credential_url: If provided, bakes this URL into the PNG metadata as an
                       OpenBadges credential reference

    Raises:
        RuntimeError: If cairosvg is not installed
    """
    if not HAS_CAIROSVG:
        raise RuntimeError(
            "cairosvg is required for PNG generation. "
            "Install it with: pip install cairosvg"
        )

    from PIL import Image, PngImagePlugin
    import io

    if linkedin_optimized:
        # Create LinkedIn-optimized image (1.91:1 aspect ratio)

        # LinkedIn recommended dimensions
        li_width = 1200
        li_height = 627

        # Render SVG to PNG at a size that fits well in the banner
        # Badge should be prominent but not fill the entire height
        badge_size = int(li_height * 0.85)  # 85% of height

        png_data = cairosvg.svg2png(
            bytestring=svg_content.encode('utf-8'),
            output_width=badge_size,
            output_height=badge_size
        )

        # Create transparent background with 1px solid black border
        # The border prevents LinkedIn from cropping away the transparent padding
        badge_img = Image.open(io.BytesIO(png_data)).convert('RGBA')
        background = Image.new('RGBA', (li_width, li_height), (0, 0, 0, 0))  # Fully transparent

        # Draw 1px solid black border
        from PIL import ImageDraw
        draw = ImageDraw.Draw(background)
        border_color = (0, 0, 0, 255)  # Black with full opacity
        # Top edge
        draw.line([(0, 0), (li_width - 1, 0)], fill=border_color, width=1)
        # Bottom edge
        draw.line([(0, li_height - 1), (li_width - 1, li_height - 1)], fill=border_color, width=1)
        # Left edge
        draw.line([(0, 0), (0, li_height - 1)], fill=border_color, width=1)
        # Right edge
        draw.line([(li_width - 1, 0), (li_width - 1, li_height - 1)], fill=border_color, width=1)

        # Center the badge on the background
        x_offset = (li_width - badge_size) // 2
        y_offset = (li_height - badge_size) // 2

        # Paste badge onto background
        background.paste(badge_img, (x_offset, y_offset), badge_img)

        # Bake credential URL if provided
        if credential_url:
            metadata = PngImagePlugin.PngInfo()
            metadata.add_text("openbadges", credential_url)
            background.save(str(output_path), 'PNG', pnginfo=metadata)
        else:
            background.save(str(output_path), 'PNG')
    else:
        # Standard square PNG
        png_data = cairosvg.svg2png(
            bytestring=svg_content.encode('utf-8'),
            output_width=width
        )

        if credential_url:
            # Load the PNG data and add metadata
            img = Image.open(io.BytesIO(png_data))
            metadata = PngImagePlugin.PngInfo()
            metadata.add_text("openbadges", credential_url)
            img.save(str(output_path), 'PNG', pnginfo=metadata)
        else:
            with open(output_path, 'wb') as f:
                f.write(png_data)


def bake_svg(svg_content: str, credential: dict) -> str:
    """
    Embed a credential into an SVG image.

    The credential is added as a base64-encoded JSON string in an
    <openbadges:credential> element within the SVG.
    """
    credential_json = json.dumps(credential, separators=(',', ':'))
    credential_b64 = base64.b64encode(credential_json.encode('utf-8')).decode('ascii')

    # Check if SVG already has xmlns:openbadges
    if 'xmlns:openbadges' not in svg_content:
        # Add namespace to root SVG element
        svg_content = re.sub(
            r'(<svg\s)',
            f'\\1xmlns:openbadges="{OPENBADGES_NS}" ',
            svg_content,
            count=1
        )

    # Create the credential element
    credential_element = f'''
  <openbadges:credential verify="https://credentials.cognipilot.org/verify">
    {credential_b64}
  </openbadges:credential>
'''

    # Check if there's already a baked credential and replace it
    if '<openbadges:credential' in svg_content:
        svg_content = re.sub(
            r'<openbadges:credential[^>]*>.*?</openbadges:credential>',
            credential_element.strip(),
            svg_content,
            flags=re.DOTALL
        )
    else:
        # Insert before closing </svg> tag
        svg_content = re.sub(
            r'(</svg>)',
            f'{credential_element}\\1',
            svg_content
        )

    return svg_content


def extract_credential(svg_content: str) -> dict | None:
    """
    Extract a baked credential from an SVG image.

    Returns the credential as a dict, or None if no credential is found.
    """
    match = re.search(
        r'<openbadges:credential[^>]*>\s*([A-Za-z0-9+/=]+)\s*</openbadges:credential>',
        svg_content
    )
    if not match:
        return None

    credential_b64 = match.group(1)
    credential_json = base64.b64decode(credential_b64).decode('utf-8')
    return json.loads(credential_json)


def main():
    parser = argparse.ArgumentParser(
        description='Bake or extract OpenBadges 3.0 credentials from SVG images'
    )
    subparsers = parser.add_subparsers(dest='command', help='Commands')

    # Bake command
    bake_parser = subparsers.add_parser('bake', help='Bake a credential into an SVG')
    bake_parser.add_argument(
        'svg',
        type=Path,
        help='Path to SVG image file'
    )
    bake_parser.add_argument(
        'credential',
        type=Path,
        help='Path to credential JSON file'
    )
    bake_parser.add_argument(
        '--output', '-o',
        type=Path,
        help='Output path for baked SVG (default: overwrites input)'
    )
    bake_parser.add_argument(
        '--name', '-n',
        type=str,
        help='Earner name to add to the badge'
    )
    bake_parser.add_argument(
        '--png',
        type=Path,
        help='Output path for PNG version of the badge'
    )
    bake_parser.add_argument(
        '--png-width',
        type=int,
        default=500,
        help='Width of PNG output in pixels (default: 500)'
    )

    # Extract command
    extract_parser = subparsers.add_parser('extract', help='Extract credential from SVG')
    extract_parser.add_argument(
        'svg',
        type=Path,
        help='Path to baked SVG image file'
    )
    extract_parser.add_argument(
        '--output', '-o',
        type=Path,
        help='Output path for extracted credential JSON (default: stdout)'
    )

    args = parser.parse_args()

    if args.command == 'bake':
        # Read SVG
        with open(args.svg) as f:
            svg_content = f.read()

        # Read credential
        with open(args.credential) as f:
            credential = json.load(f)

        # Add earner name if provided
        if args.name:
            svg_content = add_earner_name(svg_content, args.name)
            print(f"Added earner name: {args.name}", file=sys.stderr)

        # Bake credential into SVG
        baked_svg = bake_svg(svg_content, credential)

        # Output SVG
        output_path = args.output or args.svg
        with open(output_path, 'w') as f:
            f.write(baked_svg)
        print(f"Baked credential into: {output_path}", file=sys.stderr)

        # Generate PNG if requested
        if args.png:
            svg_to_png(baked_svg, args.png, width=args.png_width)
            print(f"Generated PNG: {args.png}", file=sys.stderr)

    elif args.command == 'extract':
        # Read SVG
        with open(args.svg) as f:
            svg_content = f.read()

        # Extract
        credential = extract_credential(svg_content)
        if credential is None:
            print("No credential found in SVG", file=sys.stderr)
            sys.exit(1)

        # Output
        output_json = json.dumps(credential, indent=2)
        if args.output:
            with open(args.output, 'w') as f:
                f.write(output_json)
            print(f"Extracted credential to: {args.output}", file=sys.stderr)
        else:
            print(output_json)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
