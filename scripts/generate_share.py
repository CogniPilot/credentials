#!/usr/bin/env python3
"""
Generate sharing assets for OpenBadges 3.0 credentials.

Creates:
- QR code linking to credential verification page
- LinkedIn share URL
- HTML share page with embedded credential
"""

import argparse
import base64
import json
import urllib.parse
from pathlib import Path

import qrcode
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.moduledrawers import RoundedModuleDrawer


def generate_qr_code(url: str, output_path: Path, logo_path: Path = None) -> None:
    """Generate a QR code PNG for a URL."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)

    # Create styled QR code
    img = qr.make_image(
        image_factory=StyledPilImage,
        module_drawer=RoundedModuleDrawer()
    )

    # Add logo in center if provided
    if logo_path and logo_path.exists():
        from PIL import Image
        logo = Image.open(logo_path)
        # Resize logo to fit in center
        qr_width, qr_height = img.size
        logo_max_size = qr_width // 4
        logo.thumbnail((logo_max_size, logo_max_size))
        # Calculate position
        logo_pos = ((qr_width - logo.width) // 2, (qr_height - logo.height) // 2)
        img.paste(logo, logo_pos)

    img.save(output_path)


def generate_linkedin_url(
    credential: dict,
    credential_url: str = None
) -> str:
    """Generate LinkedIn certification share URL."""
    # Extract credential info - get name from achievement if available
    subject = credential.get('credentialSubject', {})
    achievement = subject.get('achievement', {})
    name = achievement.get('name') or credential.get('name', 'Achievement')

    issuer = credential.get('issuer', {})
    issuer_name = issuer.get('name', 'Unknown') if isinstance(issuer, dict) else str(issuer)

    # Get issue date
    valid_from = credential.get('validFrom', '')
    issue_year = valid_from[:4] if valid_from else ''
    issue_month = valid_from[5:7] if len(valid_from) > 6 else ''

    # Get expiration date
    valid_until = credential.get('validUntil', '')
    expiry_year = valid_until[:4] if valid_until else ''
    expiry_month = valid_until[5:7] if len(valid_until) > 6 else ''

    # Build LinkedIn add certification URL
    params = {
        'name': name,
        'organizationName': issuer_name,
        'issueYear': issue_year,
        'issueMonth': issue_month,
    }

    # Add expiration if present
    if expiry_year:
        params['expirationYear'] = expiry_year
    if expiry_month:
        params['expirationMonth'] = expiry_month

    if credential_url:
        params['certUrl'] = credential_url

    # Get credential ID
    cred_id = credential.get('id', '')
    if cred_id:
        # Extract just the UUID part if it's a full URL
        params['certId'] = cred_id.split('/')[-1]

    # Filter out empty values
    params = {k: v for k, v in params.items() if v}

    base_url = 'https://www.linkedin.com/profile/add?startTask=CERTIFICATION_NAME'
    query = urllib.parse.urlencode(params)

    return f"{base_url}&{query}"


def generate_html_share_page(
    credential: dict,
    svg_path: Path = None,
    output_path: Path = None,
    verification_url: str = None,
    badge_image_url: str = None
) -> str:
    """Generate an HTML page for sharing the credential."""
    issuer = credential.get('issuer', {})
    issuer_name = issuer.get('name', 'Unknown') if isinstance(issuer, dict) else str(issuer)
    issuer_url = issuer.get('url', '#') if isinstance(issuer, dict) else '#'

    subject = credential.get('credentialSubject', {})
    recipient_name = subject.get('name', 'Recipient')
    achievement = subject.get('achievement', {})
    name = achievement.get('name') or credential.get('name', 'Achievement')
    description = achievement.get('description', '')

    valid_from = credential.get('validFrom', '')
    valid_until = credential.get('validUntil', '')
    issue_date = valid_from[:10] if valid_from else 'Unknown'
    expiry_date = valid_until[:10] if valid_until else None

    cred_id = credential.get('id', '')

    # Embed SVG if provided
    svg_embed = ''
    if svg_path and svg_path.exists():
        with open(svg_path) as f:
            svg_content = f.read()
        svg_embed = f'<div class="badge-image">{svg_content}</div>'

    # Generate LinkedIn URL
    linkedin_url = generate_linkedin_url(credential, verification_url)

    # Build og:image meta tag if badge image URL provided
    og_image_tag = ''
    if badge_image_url:
        og_image_tag = f'''
    <meta property="og:image" content="{badge_image_url}">
    <meta property="og:image:type" content="image/png">
    <meta property="og:image:width" content="400">
    <meta property="og:image:height" content="400">'''

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{name} - {recipient_name}</title>
    <meta property="og:title" content="{name}">
    <meta property="og:description" content="{recipient_name} earned {name} from {issuer_name}">
    <meta property="og:type" content="website">{og_image_tag}
    <style>
        * {{ box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 600px;
            margin: 0 auto;
            padding: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
        }}
        .card {{
            background: white;
            border-radius: 16px;
            padding: 32px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
        }}
        .badge-image {{
            text-align: center;
            margin-bottom: 24px;
        }}
        .badge-image svg {{
            max-width: 200px;
            height: auto;
        }}
        h1 {{
            color: #1a1a2e;
            margin: 0 0 8px 0;
            font-size: 24px;
        }}
        .recipient {{
            color: #4F46E5;
            font-size: 18px;
            margin-bottom: 16px;
        }}
        .issuer {{
            color: #666;
            font-size: 14px;
            margin-bottom: 16px;
        }}
        .description {{
            color: #444;
            line-height: 1.6;
            margin-bottom: 24px;
        }}
        .meta {{
            font-size: 12px;
            color: #888;
            border-top: 1px solid #eee;
            padding-top: 16px;
            margin-top: 16px;
        }}
        .share-buttons {{
            display: flex;
            gap: 12px;
            flex-wrap: wrap;
            margin-top: 24px;
        }}
        .btn {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 12px 20px;
            border-radius: 8px;
            text-decoration: none;
            font-weight: 500;
            font-size: 14px;
            transition: transform 0.2s;
        }}
        .btn:hover {{
            transform: translateY(-2px);
        }}
        .btn-linkedin {{
            background: #0077B5;
            color: white;
        }}
        .btn-verify {{
            background: #4F46E5;
            color: white;
        }}
        .btn-download {{
            background: #10B981;
            color: white;
        }}
        .verified {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: #D1FAE5;
            color: #065F46;
            padding: 6px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 500;
        }}
    </style>
</head>
<body>
    <div class="card">
        {svg_embed}
        <div class="verified">
            <svg width="16" height="16" fill="currentColor" viewBox="0 0 20 20">
                <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/>
            </svg>
            Verified Credential
        </div>
        <h1>{name}</h1>
        <div class="recipient">Awarded to {recipient_name}</div>
        <div class="issuer">Issued by <a href="{issuer_url}">{issuer_name}</a></div>
        <div class="description">{description}</div>

        <div class="share-buttons">
            <a href="{linkedin_url}" target="_blank" class="btn btn-linkedin">
                <svg width="20" height="20" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433c-1.144 0-2.063-.926-2.063-2.065 0-1.138.92-2.063 2.063-2.063 1.14 0 2.064.925 2.064 2.063 0 1.139-.925 2.065-2.064 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/>
                </svg>
                Add to LinkedIn
            </a>
            {f'<a href="{verification_url}" target="_blank" class="btn btn-verify">Verify</a>' if verification_url else ''}
        </div>

        <div class="meta">
            <div>Issued: {issue_date}</div>
            {f'<div>Expires: {expiry_date}</div>' if expiry_date else ''}
            <div>Credential ID: {cred_id.split('/')[-1] if cred_id else 'N/A'}</div>
        </div>
    </div>

    <script>
        // Credential data for verification
        const credential = {json.dumps(credential)};
    </script>
</body>
</html>'''

    if output_path:
        with open(output_path, 'w') as f:
            f.write(html)

    return html


def main():
    parser = argparse.ArgumentParser(
        description='Generate sharing assets for OpenBadges 3.0 credentials'
    )
    parser.add_argument(
        'credential',
        type=Path,
        help='Path to signed credential JSON file'
    )
    parser.add_argument(
        '--svg',
        type=Path,
        help='Path to baked SVG badge (for HTML embed)'
    )
    parser.add_argument(
        '--output-dir', '-o',
        type=Path,
        help='Output directory for generated files (default: same as credential)'
    )
    parser.add_argument(
        '--base-url',
        type=str,
        default='https://credentials.cognipilot.org',
        help='Base URL for credential verification'
    )
    parser.add_argument(
        '--qr-only',
        action='store_true',
        help='Only generate QR code'
    )
    parser.add_argument(
        '--linkedin-only',
        action='store_true',
        help='Only output LinkedIn URL'
    )
    args = parser.parse_args()

    # Load credential
    with open(args.credential) as f:
        credential = json.load(f)

    # Determine output directory
    output_dir = args.output_dir or args.credential.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    # Base name for outputs
    base_name = args.credential.stem

    # Build verification URL
    cred_id = credential.get('id', '').split('/')[-1]
    verification_url = f"{args.base_url}/verify.html#{cred_id}" if cred_id else None

    # Generate LinkedIn URL
    linkedin_url = generate_linkedin_url(credential, verification_url)

    if args.linkedin_only:
        print(linkedin_url)
        return

    # Generate QR code
    qr_path = output_dir / f"{base_name}-qr.png"
    qr_url = verification_url or args.credential.as_uri()
    generate_qr_code(qr_url, qr_path)
    print(f"QR code saved to: {qr_path}")

    if args.qr_only:
        return

    # Generate HTML share page
    svg_path = args.svg
    if not svg_path:
        # Try to find SVG with same name as credential
        potential_svg = args.credential.with_suffix('.svg')
        if potential_svg.exists():
            svg_path = potential_svg

    html_path = output_dir / f"{base_name}.html"
    generate_html_share_page(
        credential,
        svg_path=svg_path,
        output_path=html_path,
        verification_url=verification_url
    )
    print(f"Share page saved to: {html_path}")

    # Print LinkedIn URL
    print(f"\nLinkedIn share URL:\n{linkedin_url}")


if __name__ == '__main__':
    main()
