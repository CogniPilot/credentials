#!/usr/bin/env python3
"""
Issue a new OpenBadges 3.0 credential.

Creates a credential from an achievement template and signs it.
"""

import argparse
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sign_credential import load_private_key, sign_credential
from bake_badge import bake_svg
from generate_share import generate_qr_code, generate_linkedin_url, generate_html_share_page


# Default output directory
DEFAULT_CREDENTIALS_DIR = Path.home() / 'cognipilot_credentials'

# Default badge images directory
SCRIPT_DIR = Path(__file__).parent.parent
DEFAULT_IMAGES_DIR = SCRIPT_DIR / 'docs' / 'images'


def create_credential(
    achievement_path: Path,
    recipient_id: str,
    credential_id: str = None,
    recipient_name: str = None
) -> dict:
    """Create an unsigned credential from an achievement template."""

    # Load achievement
    with open(achievement_path) as f:
        achievement = json.load(f)

    # Generate credential ID if not provided
    if not credential_id:
        credential_uuid = str(uuid.uuid4())
        credential_id = f"https://credentials.cognipilot.org/credentials/{credential_uuid}"

    # Get issuer from achievement
    issuer = achievement.get('issuer', {})
    issuer_id = issuer.get('id', 'https://credentials.cognipilot.org/issuer')

    # Build credential
    credential = {
        "@context": [
            "https://www.w3.org/ns/credentials/v2",
            "https://purl.imsglobal.org/spec/ob/v3p0/context-3.0.3.json"
        ],
        "id": credential_id,
        "type": ["VerifiableCredential", "OpenBadgeCredential"],
        "name": achievement.get('name', 'Achievement'),
        "issuer": {
            "id": issuer_id,
            "type": ["Profile"],
            "name": issuer.get('name', 'CogniPilot Foundation'),
            "url": "https://cognipilot.org",
            "image": {
                "id": "https://credentials.cognipilot.org/images/cognipilot-logo.png",
                "type": "Image"
            }
        },
        "validFrom": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "credentialSubject": {
            "id": recipient_id,
            "type": ["AchievementSubject"],
            "achievement": {
                "id": achievement.get('id'),
                "type": ["Achievement"],
                "name": achievement.get('name'),
                "description": achievement.get('description'),
                "criteria": achievement.get('criteria'),
                "image": achievement.get('image'),
                "issuer": {
                    "id": issuer_id,
                    "type": ["Profile"],
                    "name": issuer.get('name', 'CogniPilot')
                }
            }
        }
    }

    # Add recipient name if provided
    if recipient_name:
        credential['credentialSubject']['name'] = recipient_name

    return credential


def main():
    parser = argparse.ArgumentParser(
        description='Issue a new OpenBadges 3.0 credential'
    )
    parser.add_argument(
        'achievement',
        type=Path,
        help='Path to achievement definition JSON file'
    )
    parser.add_argument(
        '--recipient', '-r',
        type=str,
        required=True,
        help='Recipient identifier (DID, email URI like mailto:user@example.com, or URL)'
    )
    parser.add_argument(
        '--recipient-name',
        type=str,
        help='Recipient display name (optional)'
    )
    parser.add_argument(
        '--key', '-k',
        type=Path,
        required=True,
        help='Path to private key JSON file for signing'
    )
    parser.add_argument(
        '--credential-id',
        type=str,
        help='Custom credential ID (default: auto-generated UUID)'
    )
    parser.add_argument(
        '--output', '-o',
        type=Path,
        help=f'Output path for signed credential (default: ~/cognipilot_credentials/<recipient-name>.json)'
    )
    parser.add_argument(
        '--output-dir',
        type=Path,
        default=DEFAULT_CREDENTIALS_DIR,
        help=f'Output directory when --output not specified (default: {DEFAULT_CREDENTIALS_DIR})'
    )
    parser.add_argument(
        '--unsigned',
        action='store_true',
        help='Output unsigned credential (skip signing)'
    )
    parser.add_argument(
        '--bake',
        type=Path,
        nargs='?',
        const='auto',
        help='Bake credential into SVG badge image. Optionally specify SVG path (default: auto-detect from achievement)'
    )
    parser.add_argument(
        '--images-dir',
        type=Path,
        default=DEFAULT_IMAGES_DIR,
        help=f'Directory containing badge SVG images (default: {DEFAULT_IMAGES_DIR})'
    )
    parser.add_argument(
        '--share',
        action='store_true',
        help='Generate sharing assets (QR code, LinkedIn URL, HTML page)'
    )
    parser.add_argument(
        '--base-url',
        type=str,
        default='https://credentials.cognipilot.org',
        help='Base URL for credential verification (default: https://credentials.cognipilot.org)'
    )
    args = parser.parse_args()

    # Create credential
    credential = create_credential(
        args.achievement,
        args.recipient,
        args.credential_id,
        args.recipient_name
    )

    # Sign unless --unsigned flag
    if not args.unsigned:
        signing_key, verification_method = load_private_key(args.key)
        credential = sign_credential(credential, signing_key, verification_method)

    # Output
    output_json = json.dumps(credential, indent=2)

    # Determine output path
    output_path = args.output
    if not output_path:
        # Auto-generate filename from recipient name or email
        if args.recipient_name:
            filename = args.recipient_name.replace(' ', '-') + '.json'
        else:
            # Extract name from mailto: or use UUID
            recipient = args.recipient
            if recipient.startswith('mailto:'):
                filename = recipient[7:].split('@')[0] + '.json'
            else:
                filename = str(uuid.uuid4()) + '.json'
        output_path = args.output_dir / filename

    # Create output directory if it doesn't exist
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w') as f:
        f.write(output_json)
    print(f"Credential saved to: {output_path}")

    # Bake into SVG if requested
    if args.bake:
        # Determine SVG path
        if args.bake == 'auto' or str(args.bake) == 'auto':
            # Auto-detect from achievement image
            with open(args.achievement) as f:
                achievement = json.load(f)
            image_info = achievement.get('image', {})
            image_url = image_info.get('id', '') if isinstance(image_info, dict) else str(image_info)

            # Extract filename from URL and look for SVG version
            if image_url:
                image_filename = image_url.split('/')[-1]
                # Try SVG version first
                svg_filename = image_filename.rsplit('.', 1)[0] + '.svg'
                svg_path = args.images_dir / svg_filename
                if not svg_path.exists():
                    # Try PNG filename as-is (might be .svg already)
                    svg_path = args.images_dir / image_filename
            else:
                # No image URL in achievement, skip baking
                svg_path = None
        else:
            svg_path = args.bake

        if not svg_path or not svg_path.exists():
            print(f"Warning: SVG badge not found at {svg_path}, skipping bake")
        else:
            # Read SVG
            with open(svg_path) as f:
                svg_content = f.read()

            # Bake credential into SVG
            baked_svg = bake_svg(svg_content, credential)

            # Output baked SVG alongside JSON
            baked_svg_path = output_path.with_suffix('.svg')
            with open(baked_svg_path, 'w') as f:
                f.write(baked_svg)
            print(f"Baked badge saved to: {baked_svg_path}")

    # Generate sharing assets if requested
    if args.share:
        # Build verification URL
        cred_id = credential.get('id', '').split('/')[-1]
        verification_url = f"{args.base_url}/verify.html#{cred_id}" if cred_id else None

        # Generate QR code
        qr_path = output_path.with_name(output_path.stem + '-qr.png')
        qr_url = verification_url or f"{args.base_url}/credentials/{cred_id}"
        generate_qr_code(qr_url, qr_path)
        print(f"QR code saved to: {qr_path}")

        # Generate HTML share page
        svg_path = output_path.with_suffix('.svg')
        if not svg_path.exists():
            svg_path = None
        html_path = output_path.with_suffix('.html')
        generate_html_share_page(
            credential,
            svg_path=svg_path,
            output_path=html_path,
            verification_url=verification_url
        )
        print(f"Share page saved to: {html_path}")

        # Print LinkedIn URL
        linkedin_url = generate_linkedin_url(credential, verification_url)
        print(f"\nLinkedIn share URL:\n{linkedin_url}")


if __name__ == '__main__':
    main()
