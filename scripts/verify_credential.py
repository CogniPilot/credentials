#!/usr/bin/env python3
"""
Verify an OpenBadges 3.0 credential signed with Data Integrity proof.

Supports the eddsa-jcs-2022 cryptosuite.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError
import base58


# Multicodec prefixes
ED25519_PUB_HEADER = bytes([0xed, 0x01])


def decode_multibase(value: str) -> bytes:
    """Decode a multibase-encoded value."""
    if value.startswith('z'):
        return base58.b58decode(value[1:])
    raise ValueError(f"Unsupported multibase prefix: {value[0]}")


def load_public_key(key_path: Path) -> tuple:
    """Load public key from JSON file."""
    with open(key_path) as f:
        key_doc = json.load(f)

    public_multibase = key_doc['publicKeyMultibase']
    decoded = decode_multibase(public_multibase)

    # Remove multicodec header
    if decoded[:2] != ED25519_PUB_HEADER:
        raise ValueError("Invalid Ed25519 public key format")

    public_bytes = decoded[2:]
    verify_key = VerifyKey(public_bytes)

    return verify_key, key_doc['id']


def jcs_canonicalize(obj) -> bytes:
    """Canonicalize JSON object using JCS (RFC 8785)."""
    return json.dumps(
        obj,
        separators=(',', ':'),
        sort_keys=True,
        ensure_ascii=False
    ).encode('utf-8')


def verify_credential(credential: dict, verify_key: VerifyKey) -> dict:
    """
    Verify a credential signed with eddsa-jcs-2022 cryptosuite.

    Returns dict with verification result and details.
    """
    result = {
        'verified': False,
        'errors': [],
        'warnings': [],
        'credential_id': credential.get('id', 'unknown'),
        'issuer': None,
        'subject': None,
        'proof': None
    }

    # Check for proof
    if 'proof' not in credential:
        result['errors'].append("No proof found in credential")
        return result

    proof = credential['proof']
    result['proof'] = {
        'type': proof.get('type'),
        'cryptosuite': proof.get('cryptosuite'),
        'created': proof.get('created'),
        'verificationMethod': proof.get('verificationMethod')
    }

    # Validate proof type
    if proof.get('type') != 'DataIntegrityProof':
        result['errors'].append(f"Unsupported proof type: {proof.get('type')}")
        return result

    if proof.get('cryptosuite') != 'eddsa-jcs-2022':
        result['errors'].append(f"Unsupported cryptosuite: {proof.get('cryptosuite')}")
        return result

    # Extract proof value
    proof_value = proof.get('proofValue')
    if not proof_value:
        result['errors'].append("No proofValue in proof")
        return result

    try:
        signature = decode_multibase(proof_value)
    except Exception as e:
        result['errors'].append(f"Failed to decode proofValue: {e}")
        return result

    # Recreate proof config (without proofValue and @context)
    proof_config = {
        'type': proof['type'],
        'cryptosuite': proof['cryptosuite'],
        'verificationMethod': proof['verificationMethod'],
        'created': proof['created'],
        'proofPurpose': proof['proofPurpose']
    }

    # Get credential without proof
    credential_copy = {k: v for k, v in credential.items() if k != 'proof'}

    # Canonicalize and hash
    canonical_proof = jcs_canonicalize(proof_config)
    canonical_credential = jcs_canonicalize(credential_copy)

    proof_hash = hashlib.sha256(canonical_proof).digest()
    credential_hash = hashlib.sha256(canonical_credential).digest()
    combined = proof_hash + credential_hash

    # Verify signature
    try:
        verify_key.verify(combined, signature)
        result['verified'] = True
    except BadSignatureError:
        result['errors'].append("Signature verification failed")
        return result

    # Extract additional info
    issuer = credential.get('issuer')
    if isinstance(issuer, dict):
        result['issuer'] = issuer.get('name', issuer.get('id'))
    else:
        result['issuer'] = issuer

    subject = credential.get('credentialSubject', {})
    result['subject'] = subject.get('id', 'unknown')

    achievement = subject.get('achievement', {})
    result['achievement'] = achievement.get('name', 'unknown')

    return result


def main():
    parser = argparse.ArgumentParser(
        description='Verify an OpenBadges 3.0 credential'
    )
    parser.add_argument(
        'credential',
        type=Path,
        help='Path to signed credential JSON file'
    )
    parser.add_argument(
        '--key', '-k',
        type=Path,
        required=True,
        help='Path to public key JSON file'
    )
    parser.add_argument(
        '--json', '-j',
        action='store_true',
        help='Output result as JSON'
    )
    args = parser.parse_args()

    # Load credential
    with open(args.credential) as f:
        credential = json.load(f)

    # Load public key
    verify_key, key_id = load_public_key(args.key)

    # Verify
    result = verify_credential(credential, verify_key)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if result['verified']:
            print("✓ Credential verified successfully!")
            print(f"  Credential ID: {result['credential_id']}")
            print(f"  Issuer: {result['issuer']}")
            print(f"  Subject: {result['subject']}")
            print(f"  Achievement: {result.get('achievement', 'N/A')}")
            print(f"  Signed: {result['proof']['created']}")
        else:
            print("✗ Credential verification failed!")
            for error in result['errors']:
                print(f"  Error: {error}")
            sys.exit(1)


if __name__ == '__main__':
    main()
