#!/usr/bin/env python3
"""
Sign an OpenBadges 3.0 credential using Ed25519 and Data Integrity proof.

Uses the eddsa-rdfc-2022 cryptosuite which canonicalizes using RDF Dataset
Canonicalization (RDFC-1.0) for compatibility with 1EdTech validators.
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from nacl.signing import SigningKey
import base58

try:
    from pyld import jsonld
    HAS_PYLD = True
except ImportError:
    HAS_PYLD = False

# Local cache of JSON-LD contexts (URL -> local filename)
# These are stored in the contexts/ directory relative to this script
CONTEXT_CACHE = {
    "https://purl.imsglobal.org/spec/ob/v3p0/context-3.0.3.json": "ob-v3p0-context-3.0.3.json",
    "https://www.w3.org/ns/credentials/v2": "credentials-v2.json",
    "https://w3id.org/security/data-integrity/v2": "data-integrity-v2.json",
}


def _get_contexts_dir() -> Path:
    """Get the path to the contexts directory."""
    return Path(__file__).parent.parent / "contexts"


def _cached_document_loader(url, options={}):
    """
    Document loader that uses local cached copies of JSON-LD contexts.

    Falls back to network requests for URLs not in the cache.
    """
    if url in CONTEXT_CACHE:
        context_path = _get_contexts_dir() / CONTEXT_CACHE[url]
        if context_path.exists():
            with open(context_path) as f:
                document = json.load(f)
            return {
                "contentType": "application/ld+json",
                "contextUrl": None,
                "documentUrl": url,
                "document": document,
            }
    # Fallback to network for uncached URLs
    return jsonld.requests_document_loader()(url, options)


if HAS_PYLD:
    jsonld.set_document_loader(_cached_document_loader)


# Multicodec prefixes
ED25519_PRIV_HEADER = bytes([0x80, 0x26])


def decode_multibase(value: str) -> bytes:
    """Decode a multibase-encoded value."""
    if value.startswith('z'):
        return base58.b58decode(value[1:])
    raise ValueError(f"Unsupported multibase prefix: {value[0]}")


def load_private_key(key_path: Path) -> tuple:
    """Load private key from JSON file."""
    with open(key_path) as f:
        key_doc = json.load(f)

    secret_multibase = key_doc['secretKeyMultibase']
    decoded = decode_multibase(secret_multibase)

    # Remove multicodec header
    if decoded[:2] != ED25519_PRIV_HEADER:
        raise ValueError("Invalid Ed25519 private key format")

    private_bytes = decoded[2:]
    signing_key = SigningKey(private_bytes)

    return signing_key, key_doc['id']


def jcs_canonicalize(obj) -> bytes:
    """
    Canonicalize JSON object using JCS (RFC 8785).

    JCS rules:
    - Object keys sorted lexicographically by Unicode code points
    - No whitespace
    - Numbers serialized without unnecessary precision
    - Strings use minimal escaping
    """
    return json.dumps(
        obj,
        separators=(',', ':'),
        sort_keys=True,
        ensure_ascii=False
    ).encode('utf-8')


def rdfc_canonicalize(obj) -> bytes:
    """
    Canonicalize JSON-LD object using RDF Dataset Canonicalization (RDFC-1.0).

    This uses PyLD to convert JSON-LD to normalized N-Quads format.
    """
    if not HAS_PYLD:
        raise RuntimeError(
            "PyLD is required for eddsa-rdfc-2022 cryptosuite. "
            "Install it with: pip install pyld"
        )

    # Normalize to N-Quads using URDNA2015 algorithm (RDFC-1.0 compatible)
    normalized = jsonld.normalize(
        obj,
        {'algorithm': 'URDNA2015', 'format': 'application/n-quads'}
    )
    return normalized.encode('utf-8')


def create_proof_config(verification_method: str, created: str) -> dict:
    """Create the proof configuration object."""
    return {
        "type": "DataIntegrityProof",
        "cryptosuite": "eddsa-rdfc-2022",
        "verificationMethod": verification_method,
        "created": created,
        "proofPurpose": "assertionMethod"
    }


def sign_credential(credential: dict, signing_key: SigningKey, verification_method: str) -> dict:
    """
    Sign a credential using eddsa-rdfc-2022 cryptosuite.

    Process:
    1. Create proof configuration with @context for canonicalization
    2. Canonicalize proof config and credential using RDFC-1.0
    3. Hash both canonicalized forms
    4. Concatenate hashes and sign
    5. Add proof to credential (without @context)
    """
    # Remove any existing proof
    credential_copy = {k: v for k, v in credential.items() if k != 'proof'}

    # Create proof configuration
    created = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    proof_config = create_proof_config(verification_method, created)

    # For RDFC canonicalization, proof config needs @context
    proof_config_with_context = {
        "@context": [
            "https://www.w3.org/ns/credentials/v2",
            "https://w3id.org/security/data-integrity/v2"
        ],
        **proof_config
    }

    # Canonicalize both documents using RDFC-1.0
    canonical_proof = rdfc_canonicalize(proof_config_with_context)
    canonical_credential = rdfc_canonicalize(credential_copy)

    # Hash both (SHA-256)
    proof_hash = hashlib.sha256(canonical_proof).digest()
    credential_hash = hashlib.sha256(canonical_credential).digest()

    # Concatenate hashes and sign
    combined = proof_hash + credential_hash
    signature = signing_key.sign(combined).signature

    # Encode signature as multibase
    proof_value = 'z' + base58.b58encode(signature).decode('ascii')

    # Create complete proof (no separate @context when embedded in credential)
    proof = {
        **proof_config,
        "proofValue": proof_value
    }

    # Add proof to credential
    signed_credential = credential_copy.copy()
    signed_credential['proof'] = proof

    return signed_credential


def main():
    parser = argparse.ArgumentParser(
        description='Sign an OpenBadges 3.0 credential'
    )
    parser.add_argument(
        'credential',
        type=Path,
        help='Path to unsigned credential JSON file'
    )
    parser.add_argument(
        '--key', '-k',
        type=Path,
        required=True,
        help='Path to private key JSON file'
    )
    parser.add_argument(
        '--output', '-o',
        type=Path,
        help='Output path for signed credential (default: stdout)'
    )
    args = parser.parse_args()

    # Load credential
    with open(args.credential) as f:
        credential = json.load(f)

    # Load private key
    signing_key, verification_method = load_private_key(args.key)

    # Sign credential
    signed_credential = sign_credential(credential, signing_key, verification_method)

    # Output
    output_json = json.dumps(signed_credential, indent=2)

    if args.output:
        with open(args.output, 'w') as f:
            f.write(output_json)
        print(f"Signed credential saved to: {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == '__main__':
    main()
