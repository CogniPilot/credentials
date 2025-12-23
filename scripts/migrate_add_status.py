#!/usr/bin/env python3
"""
ONE-TIME MIGRATION SCRIPT

Adds credentialStatus field to all existing credentials and re-signs them.
This enables revocation support for credentials issued before the status
list feature was added.

Run once and delete this script afterward.

Usage:
    python migrate_add_status.py --key ../keys/key-1-private.json
    python migrate_add_status.py --key ../keys/key-1-private.json --dry-run
"""

import argparse
import json
from pathlib import Path

from sign_credential import load_private_key, sign_credential
from bake_badge import bake_svg, add_earner_name, svg_to_png
from status_list import create_credential_status, update_status_list

# Directory paths
SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent
PROFILES_DIR = REPO_ROOT / 'docs' / 'profile'
BADGES_DIR = REPO_ROOT / 'docs' / 'images' / 'badges'
ACHIEVEMENTS_DIR = REPO_ROOT / 'achievements'


def migrate_credential(cred_file: Path, signing_key, verification_method, dry_run: bool = False) -> bool:
    """
    Add credentialStatus to a credential and re-sign it.

    Returns True if migrated, False if skipped.
    """
    with open(cred_file) as f:
        credential = json.load(f)

    # Skip if already has credentialStatus
    if 'credentialStatus' in credential:
        print(f"  Skipping (already has status): {cred_file}")
        return False

    cred_dir = cred_file.parent
    wallet_slug = cred_dir.parent.name
    achievement_id = cred_dir.name

    print(f"  Migrating: {wallet_slug}/{achievement_id}")

    if dry_run:
        return True

    # Remove existing proof (will re-sign)
    credential_without_proof = {k: v for k, v in credential.items() if k != 'proof'}

    # Add credentialStatus
    credential_without_proof['credentialStatus'] = create_credential_status(wallet_slug, achievement_id)

    # Re-sign the credential
    signed_credential = sign_credential(credential_without_proof, signing_key, verification_method)

    # Save updated credential
    with open(cred_file, 'w') as f:
        json.dump(signed_credential, f, indent=2)

    # Regenerate baked badges
    subject = signed_credential.get('credentialSubject', {})
    recipient_name = subject.get('name', '')
    achievement = subject.get('achievement', {})
    image_info = achievement.get('image', {})
    image_url = image_info.get('id', '') if isinstance(image_info, dict) else str(image_info)

    if image_url:
        svg_filename = image_url.split('/')[-1]
        svg_path = BADGES_DIR / svg_filename

        if svg_path.exists():
            with open(svg_path) as f:
                svg_content = f.read()

            # Add earner name and bake credential
            svg_with_name = add_earner_name(svg_content, recipient_name)
            baked_svg = bake_svg(svg_with_name, signed_credential)

            # Save baked SVG
            profile_svg_path = cred_dir / "badge.svg"
            with open(profile_svg_path, 'w') as f:
                f.write(baked_svg)

            # Generate PNG
            profile_png_path = cred_dir / "badge.png"
            try:
                svg_to_png(baked_svg, profile_png_path, width=500, credential=signed_credential)
            except RuntimeError as e:
                print(f"    Warning: Could not generate PNG: {e}")

    return True


def main():
    parser = argparse.ArgumentParser(
        description='One-time migration: Add credentialStatus to existing credentials'
    )
    parser.add_argument(
        '--key', '-k',
        type=Path,
        required=True,
        help='Path to private key JSON file'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be migrated without making changes'
    )
    args = parser.parse_args()

    print("=" * 60)
    print("CREDENTIAL STATUS MIGRATION")
    print("=" * 60)

    if args.dry_run:
        print("DRY RUN - No changes will be made\n")

    # Load signing key
    signing_key, verification_method = load_private_key(args.key)

    # Find all credentials
    credential_files = list(PROFILES_DIR.glob('*/*/credential.json'))
    print(f"Found {len(credential_files)} credential(s)\n")

    migrated = 0
    skipped = 0

    for cred_file in sorted(credential_files):
        if migrate_credential(cred_file, signing_key, verification_method, args.dry_run):
            migrated += 1
        else:
            skipped += 1

    print(f"\n{'=' * 60}")
    print(f"Migration complete!")
    print(f"  Migrated: {migrated}")
    print(f"  Skipped:  {skipped}")
    print("=" * 60)

    if not args.dry_run and migrated > 0:
        # Update the status list
        print("\nUpdating status list...")
        status_path = update_status_list(args.key)
        print(f"Status list saved to: {status_path}")

        print("\nDONE! You can now delete this migration script.")


if __name__ == '__main__':
    main()
