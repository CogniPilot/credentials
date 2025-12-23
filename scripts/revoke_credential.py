#!/usr/bin/env python3
"""
Revoke a previously issued credential.

This script marks a credential as revoked in the status registry and regenerates
the status list credential. Revoked credentials will fail verification when the
verifier checks the status list.

Usage:
    python revoke_credential.py --credential wallet-slug/achievement-id
    python revoke_credential.py --email user@example.com --achievement achievement-id
    python revoke_credential.py --list  # Show all credentials and their status
    python revoke_credential.py --unrevoke wallet-slug/achievement-id  # Undo revocation
"""

import argparse
import json
import sys
from pathlib import Path

from status_list import (
    load_status_registry,
    revoke_credential,
    unrevoke_credential,
    update_status_list,
    is_revoked
)

# Directory paths
SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent
KEYS_DIR = REPO_ROOT / 'keys'
PROFILES_DIR = REPO_ROOT / 'docs' / 'profile'
WALLET_REGISTRY_PATH = REPO_ROOT / 'wallet-registry.json'


def normalize_email(email: str) -> str:
    """Normalize email to lowercase and strip whitespace."""
    return email.lower().strip()


def get_wallet_slug_for_email(email: str) -> str | None:
    """Look up wallet slug for an email address."""
    if not WALLET_REGISTRY_PATH.exists():
        return None

    with open(WALLET_REGISTRY_PATH) as f:
        registry = json.load(f)

    normalized = normalize_email(email)
    return registry.get("email_index", {}).get(normalized)


def find_credential(email: str = None, achievement_id: str = None, credential_id: str = None) -> str | None:
    """
    Find a credential by email+achievement or full credential_id.

    Returns the credential_id (wallet-slug/achievement-id) or None.
    """
    if credential_id:
        # Validate it exists
        parts = credential_id.split('/')
        if len(parts) != 2:
            print(f"Error: Invalid credential ID format. Expected 'wallet-slug/achievement-id'")
            return None

        wallet_slug, ach_id = parts
        cred_path = PROFILES_DIR / wallet_slug / ach_id / 'credential.json'
        if not cred_path.exists():
            print(f"Error: Credential not found: {credential_id}")
            return None

        return credential_id

    if email and achievement_id:
        wallet_slug = get_wallet_slug_for_email(email)
        if not wallet_slug:
            print(f"Error: No wallet found for email: {email}")
            return None

        cred_path = PROFILES_DIR / wallet_slug / achievement_id / 'credential.json'
        if not cred_path.exists():
            print(f"Error: Credential not found: {wallet_slug}/{achievement_id}")
            return None

        return f"{wallet_slug}/{achievement_id}"

    return None


def list_credentials():
    """List all credentials and their revocation status."""
    registry = load_status_registry()

    if not registry["credentials"]:
        print("No credentials in status registry.")
        return

    print(f"\n{'Credential ID':<50} {'Index':<8} {'Status':<10} {'Revoked At'}")
    print("-" * 90)

    for cred_id, info in sorted(registry["credentials"].items()):
        status = "REVOKED" if info["revoked"] else "Active"
        revoked_at = info.get("revoked_at", "-") or "-"
        print(f"{cred_id:<50} {info['index']:<8} {status:<10} {revoked_at}")

    print(f"\nTotal: {len(registry['credentials'])} credential(s)")
    revoked_count = sum(1 for c in registry["credentials"].values() if c["revoked"])
    print(f"Revoked: {revoked_count}")


def main():
    parser = argparse.ArgumentParser(
        description='Revoke or manage credential revocation status'
    )
    parser.add_argument(
        '--credential', '-c',
        type=str,
        help='Credential ID in format: wallet-slug/achievement-id'
    )
    parser.add_argument(
        '--email', '-e',
        type=str,
        help='Email address of credential holder'
    )
    parser.add_argument(
        '--achievement', '-a',
        type=str,
        help='Achievement ID'
    )
    parser.add_argument(
        '--unrevoke',
        type=str,
        metavar='CREDENTIAL_ID',
        help='Remove revocation from a credential'
    )
    parser.add_argument(
        '--list', '-l',
        action='store_true',
        help='List all credentials and their status'
    )
    parser.add_argument(
        '--key', '-k',
        type=Path,
        default=KEYS_DIR / 'key-1-private.json',
        help='Path to private key for signing status list'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making changes'
    )
    args = parser.parse_args()

    if args.list:
        list_credentials()
        return

    if args.unrevoke:
        credential_id = find_credential(credential_id=args.unrevoke)
        if not credential_id:
            sys.exit(1)

        if args.dry_run:
            print(f"Would unrevoke: {credential_id}")
            return

        if not is_revoked(credential_id):
            print(f"Credential is not revoked: {credential_id}")
            return

        if unrevoke_credential(credential_id):
            print(f"Unrevoked: {credential_id}")
            status_path = update_status_list(args.key)
            print(f"Status list updated: {status_path}")
        else:
            print(f"Failed to unrevoke: {credential_id}")
            sys.exit(1)
        return

    # Handle revocation
    credential_id = None

    if args.credential:
        credential_id = find_credential(credential_id=args.credential)
    elif args.email and args.achievement:
        credential_id = find_credential(email=args.email, achievement_id=args.achievement)
    else:
        parser.print_help()
        print("\nError: Must specify --credential OR (--email AND --achievement)")
        sys.exit(1)

    if not credential_id:
        sys.exit(1)

    if args.dry_run:
        print(f"Would revoke: {credential_id}")
        return

    if is_revoked(credential_id):
        print(f"Credential is already revoked: {credential_id}")
        return

    if revoke_credential(credential_id):
        print(f"Revoked: {credential_id}")
        status_path = update_status_list(args.key)
        print(f"Status list updated: {status_path}")
    else:
        print(f"Failed to revoke: {credential_id}")
        sys.exit(1)


if __name__ == '__main__':
    main()
