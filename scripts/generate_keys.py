#!/usr/bin/env python3
"""
Generate Ed25519 keypair for OpenBadges 3.0 credential signing.

Outputs keys in Multikey format as required by the Data Integrity EdDSA Cryptosuites v1.0.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from nacl.signing import SigningKey
import base58


# Multicodec prefixes for Ed25519 keys
ED25519_PUB_HEADER = bytes([0xed, 0x01])  # ed25519-pub multicodec
ED25519_PRIV_HEADER = bytes([0x80, 0x26])  # ed25519-priv multicodec


def generate_keypair():
    """Generate a new Ed25519 keypair."""
    signing_key = SigningKey.generate()
    verify_key = signing_key.verify_key
    return signing_key, verify_key


def encode_multibase(prefix: str, data: bytes) -> str:
    """Encode bytes as multibase with given prefix."""
    if prefix == 'z':
        return 'z' + base58.b58encode(data).decode('ascii')
    raise ValueError(f"Unsupported multibase prefix: {prefix}")


def create_multikey_public(verify_key) -> str:
    """Create multibase-encoded public key in Multikey format."""
    public_bytes = bytes(verify_key)
    multicodec_key = ED25519_PUB_HEADER + public_bytes
    return encode_multibase('z', multicodec_key)


def create_multikey_private(signing_key) -> str:
    """Create multibase-encoded private key in Multikey format."""
    private_bytes = bytes(signing_key)
    multicodec_key = ED25519_PRIV_HEADER + private_bytes
    return encode_multibase('z', multicodec_key)


def main():
    parser = argparse.ArgumentParser(
        description='Generate Ed25519 keypair for OpenBadges 3.0 signing'
    )
    parser.add_argument(
        '--output-dir', '-o',
        type=Path,
        default=Path('keys'),
        help='Output directory for key files (default: keys)'
    )
    parser.add_argument(
        '--key-id',
        type=str,
        default='key-1',
        help='Key identifier (default: key-1)'
    )
    parser.add_argument(
        '--issuer-id',
        type=str,
        default='https://credentials.cognipilot.org/issuer',
        help='Issuer ID URL'
    )
    args = parser.parse_args()

    # Create output directory
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Generate keypair
    signing_key, verify_key = generate_keypair()

    public_multikey = create_multikey_public(verify_key)
    private_multikey = create_multikey_private(signing_key)

    # Verification method ID
    verification_method_id = f"{args.issuer_id}#{args.key_id}"

    # Create public key document (for issuer profile)
    public_key_doc = {
        "id": verification_method_id,
        "type": "Multikey",
        "controller": args.issuer_id,
        "publicKeyMultibase": public_multikey
    }

    # Create private key document (keep secure!)
    private_key_doc = {
        "id": verification_method_id,
        "type": "Multikey",
        "controller": args.issuer_id,
        "publicKeyMultibase": public_multikey,
        "secretKeyMultibase": private_multikey
    }

    # Save public key
    public_key_path = args.output_dir / f"{args.key_id}-public.json"
    with open(public_key_path, 'w') as f:
        json.dump(public_key_doc, f, indent=2)
    print(f"Public key saved to: {public_key_path}")

    # Save private key with restrictive permissions
    private_key_path = args.output_dir / f"{args.key_id}-private.json"
    with open(private_key_path, 'w') as f:
        json.dump(private_key_doc, f, indent=2)
    os.chmod(private_key_path, 0o600)
    print(f"Private key saved to: {private_key_path}")

    print(f"\nVerification Method ID: {verification_method_id}")
    print(f"Public Key Multibase: {public_multikey}")
    print("\nAdd the following to your issuer profile:")
    print(json.dumps({
        "verificationMethod": [public_key_doc]
    }, indent=2))


if __name__ == '__main__':
    main()
