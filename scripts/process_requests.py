#!/usr/bin/env python3
"""
Process credential requests from JSON files.

Reads request files from the requests/ directory and generates files in
docs/profile/<wallet-slug>/<achievement-id>/:
- credential.json: Signed verifiable credential
- badge.svg: Baked SVG badge with earner name and embedded credential
- badge.png: PNG badge with embedded credential URL
- index.html: Individual credential page for sharing

Also generates a wallet page at docs/profile/<wallet-slug>/wallet/index.html
showing all credentials for the recipient.

Request types:
- "issue" (default): Issue a new credential
- "update": Update an existing credential (can change email to move wallets)
- "rename_wallet": Rename a wallet slug while keeping email association

Wallet identification:
- Wallets are identified by a name-based slug (e.g., "benjamin-perseghetti")
- Email addresses are mapped to wallet slugs in the wallet registry
- Same email always maps to the same wallet
"""

import argparse
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from sign_credential import load_private_key, sign_credential
from bake_badge import bake_svg, add_earner_name, svg_to_png
from generate_share import generate_linkedin_url


# Directory paths (relative to repository root)
SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent
ACHIEVEMENTS_DIR = REPO_ROOT / 'achievements'
BADGES_DIR = REPO_ROOT / 'docs' / 'images' / 'badges'
REQUESTS_DIR = REPO_ROOT / 'requests'
PROFILES_DIR = REPO_ROOT / 'docs' / 'profile'
KEYS_DIR = REPO_ROOT / 'keys'
WALLET_REGISTRY_PATH = REPO_ROOT / 'wallet-registry.json'

BASE_URL = 'https://credentials.cognipilot.org'


def normalize_email(email: str) -> str:
    """Normalize email to lowercase and strip whitespace."""
    return email.lower().strip()


def name_to_slug(name: str) -> str:
    """
    Convert a name to a URL-safe slug.

    Example: "Benjamin Perseghetti" -> "benjamin-perseghetti"
    """
    slug = name.lower().strip()
    # Replace spaces and underscores with hyphens
    slug = re.sub(r'[\s_]+', '-', slug)
    # Remove any non-alphanumeric chars except hyphens
    slug = re.sub(r'[^a-z0-9-]', '', slug)
    # Collapse multiple hyphens
    slug = re.sub(r'-+', '-', slug)
    # Remove leading/trailing hyphens
    slug = slug.strip('-')
    return slug


def load_wallet_registry() -> dict:
    """
    Load the wallet registry mapping emails to wallet slugs.

    Registry format:
    {
        "wallets": {
            "benjamin-perseghetti": {
                "emails": ["bperseghetti@cognipilot.org"],
                "display_name": "Benjamin Perseghetti",
                "created_at": "2025-01-01T00:00:00Z"
            }
        },
        "email_index": {
            "bperseghetti@cognipilot.org": "benjamin-perseghetti"
        }
    }
    """
    if WALLET_REGISTRY_PATH.exists():
        with open(WALLET_REGISTRY_PATH) as f:
            return json.load(f)
    return {"wallets": {}, "email_index": {}}


def save_wallet_registry(registry: dict) -> None:
    """Save the wallet registry to disk."""
    with open(WALLET_REGISTRY_PATH, 'w') as f:
        json.dump(registry, f, indent=2)


def get_wallet_slug_for_email(email: str, registry: dict) -> str | None:
    """Look up wallet slug for an email address."""
    normalized = normalize_email(email)
    return registry.get("email_index", {}).get(normalized)


def register_wallet(
    slug: str,
    email: str,
    display_name: str,
    registry: dict
) -> None:
    """Register a new wallet or add email to existing wallet."""
    normalized_email = normalize_email(email)

    if slug not in registry["wallets"]:
        registry["wallets"][slug] = {
            "emails": [],
            "display_name": display_name,
            "created_at": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        }

    # Add email if not already in wallet
    if normalized_email not in registry["wallets"][slug]["emails"]:
        registry["wallets"][slug]["emails"].append(normalized_email)

    # Update email index
    registry["email_index"][normalized_email] = slug

    # Update display name if provided
    if display_name:
        registry["wallets"][slug]["display_name"] = display_name


def rename_wallet(
    old_slug: str,
    new_slug: str,
    registry: dict,
    new_display_name: str = None
) -> bool:
    """
    Rename a wallet slug while preserving email associations.

    Returns True if successful, False if wallet not found or new slug exists.
    """
    if old_slug not in registry["wallets"]:
        return False

    if new_slug in registry["wallets"] and new_slug != old_slug:
        return False

    # Get wallet data
    wallet_data = registry["wallets"].pop(old_slug)

    # Update display name if provided
    if new_display_name:
        wallet_data["display_name"] = new_display_name

    wallet_data["renamed_at"] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    wallet_data["previous_slug"] = old_slug

    # Save under new slug
    registry["wallets"][new_slug] = wallet_data

    # Update email index
    for email in wallet_data["emails"]:
        registry["email_index"][email] = new_slug

    return True


def find_existing_credential(achievement_id: str, email: str = None) -> tuple:
    """
    Find an existing credential by achievement ID and optionally email.

    Returns: (wallet_slug, credential_dir) or (None, None) if not found
    """
    registry = load_wallet_registry()

    # If email provided, look up wallet slug first
    if email:
        wallet_slug = get_wallet_slug_for_email(email, registry)
        if wallet_slug:
            cred_dir = PROFILES_DIR / wallet_slug / achievement_id
            if cred_dir.exists():
                return wallet_slug, cred_dir

    # Fallback: search all profiles
    if PROFILES_DIR.exists():
        for profile_path in PROFILES_DIR.iterdir():
            if not profile_path.is_dir():
                continue

            cred_dir = profile_path / achievement_id
            if cred_dir.exists():
                cred_file = cred_dir / 'credential.json'
                if cred_file.exists():
                    if email:
                        # Verify email matches
                        with open(cred_file) as f:
                            cred = json.load(f)
                        subject = cred.get('credentialSubject', {})
                        cred_email = subject.get('id', '').replace('mailto:', '')
                        if normalize_email(cred_email) == normalize_email(email):
                            return profile_path.name, cred_dir
                    else:
                        return profile_path.name, cred_dir

    return None, None


def create_credential(
    achievement: dict,
    recipient_email: str,
    recipient_name: str,
    wallet_slug: str,
    achievement_id: str,
    valid_from: str = None,
    valid_until: str = None
) -> dict:
    """Create an unsigned credential from an achievement and recipient info."""

    issuer = achievement.get('issuer', {})
    issuer_id = 'did:web:credentials.cognipilot.org'

    if not valid_from:
        valid_from = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    credential_id = f"{BASE_URL}/profile/{wallet_slug}/{achievement_id}"

    credential = {
        "@context": [
            "https://www.w3.org/ns/credentials/v2",
            "https://purl.imsglobal.org/spec/ob/v3p0/context-3.0.3.json"
        ],
        "id": credential_id,
        "type": ["VerifiableCredential", "OpenBadgeCredential"],
        "issuer": {
            "type": "Profile",
            "id": issuer_id,
            "name": issuer.get('name', 'CogniPilot Foundation'),
            "url": "https://cognipilot.org"
        },
        "validFrom": valid_from,
        "credentialSubject": {
            "id": f"mailto:{normalize_email(recipient_email)}",
            "type": ["AchievementSubject"],
            "name": recipient_name,
            "achievement": {
                "id": achievement.get('id'),
                "type": "Achievement",
                "achievementType": achievement.get('achievementType'),
                "name": achievement.get('name'),
                "description": achievement.get('description'),
                "image": achievement.get('image'),
                "criteria": achievement.get('criteria')
            }
        }
    }

    if valid_until:
        credential['validUntil'] = valid_until

    return credential


def generate_wallet_page(
    wallet_slug: str,
    recipient_name: str,
    credentials: list,
    output_path: Path
) -> None:
    """Generate a wallet page showing all credentials for a recipient."""

    credential_cards = []
    for cred in credentials:
        subject = cred.get('credentialSubject', {})
        achievement = subject.get('achievement', {})
        achievement_name = achievement.get('name', 'Achievement')
        achievement_type = achievement.get('achievementType', '')
        # Strip namespace prefix for display (e.g., "ext:Role" -> "Role")
        if ':' in achievement_type:
            achievement_type = achievement_type.split(':')[-1]

        image_info = achievement.get('image', {})
        image_url = image_info.get('id', '') if isinstance(image_info, dict) else str(image_info)
        if image_url:
            image_url = image_url.replace('.svg', '.png')

        cred_id = cred.get('id', '')
        cred_slug = cred_id.split('/')[-1] if cred_id else ''
        cred_url = f"/profile/{wallet_slug}/{cred_slug}"

        valid_from = cred.get('validFrom', '')[:10] if cred.get('validFrom') else ''

        card = f'''
        <a href="{cred_url}" class="credential-card">
            <div class="credential-image">
                <img src="{image_url}" alt="{achievement_name}">
            </div>
            <div class="credential-info">
                <h3>{achievement_name}</h3>
                <p class="credential-type">{achievement_type}</p>
                <p class="credential-date">Issued: {valid_from}</p>
            </div>
        </a>'''
        credential_cards.append(card)

    cards_html = '\n'.join(credential_cards)

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <link rel="icon" type="image/png" href="/images/favicon.png">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{recipient_name} - Credential Wallet | CogniPilot</title>
    <meta property="og:title" content="{recipient_name}'s Credentials">
    <meta property="og:description" content="View verified credentials for {recipient_name} from CogniPilot Foundation">
    <meta property="og:type" content="profile">
    <link rel="stylesheet" href="/css/style.css">
    <style>
        .wallet-header {{
            text-align: center;
            padding: 48px 0 32px;
            border-bottom: 1px solid var(--color-border);
            margin-bottom: 32px;
        }}
        .wallet-header h1 {{
            margin-bottom: 8px;
        }}
        .wallet-header p {{
            color: var(--color-text-secondary);
        }}
        .credentials-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 24px;
            padding-bottom: 48px;
        }}
        .credential-card {{
            background: var(--color-bg-card);
            border-radius: var(--radius-xl);
            overflow: hidden;
            box-shadow: var(--shadow-md);
            transition: all 0.3s;
            display: block;
            color: inherit;
            text-decoration: none;
            border: 1px solid var(--color-border);
        }}
        .credential-card:hover {{
            transform: translateY(-4px);
            box-shadow: var(--shadow-xl);
            border-color: var(--color-primary);
        }}
        .credential-image {{
            background: linear-gradient(135deg, var(--color-bg-darker) 0%, var(--color-bg-card) 100%);
            padding: 24px;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 160px;
        }}
        .credential-image img {{
            max-width: 120px;
            max-height: 120px;
            object-fit: contain;
        }}
        .credential-info {{
            padding: 20px;
        }}
        .credential-info h3 {{
            margin-bottom: 8px;
            font-size: 1.1rem;
        }}
        .credential-type {{
            color: var(--color-primary);
            font-size: 0.875rem;
            font-weight: 500;
            margin-bottom: 4px;
        }}
        .credential-date {{
            color: var(--color-text-muted);
            font-size: 0.75rem;
        }}
        .credential-count {{
            color: var(--color-text-muted);
            font-size: 0.875rem;
            margin-bottom: 24px;
        }}
        .update-link {{
            margin-top: 24px;
            font-size: 0.75rem;
            text-align: center;
        }}
        .update-link a {{
            color: var(--color-text-muted);
            opacity: 0.7;
        }}
        .update-link a:hover {{
            color: var(--color-primary);
            opacity: 1;
        }}
    </style>
</head>
<body>
    <nav class="navbar">
        <div class="container nav-container">
            <a href="/" class="nav-brand">
                <img src="/images/cognipilot-logo.png" alt="CogniPilot" class="nav-logo">
                <span>Credentials</span>
            </a>
            <div class="nav-links">
                <a href="/" class="nav-link">Home</a>
                <a href="/issuer" class="nav-link">Issuer</a>
                <a href="/verify" class="nav-link">Verify</a>
            </div>
        </div>
    </nav>

    <main class="container">
        <div class="wallet-header">
            <h1>{recipient_name}</h1>
            <p>Credential Wallet</p>
        </div>

        <p class="credential-count">{len(credentials)} credential(s)</p>

        <div class="credentials-grid">
            {cards_html}
        </div>

        <p class="update-link"><a href="https://github.com/CogniPilot/credentials/issues/new?template=update-credential.yml" target="_blank">Update email or profile URL</a></p>
    </main>

    <footer class="footer">
        <div class="container">
            <div class="footer-content">
                <div class="footer-brand">
                    <img src="/images/cognipilot-logo.png" alt="CogniPilot" class="footer-logo">
                    <span>CogniPilot Credentials</span>
                </div>
                <div class="footer-links">
                    <a href="https://cognipilot.org">CogniPilot.org</a>
                    <a href="https://github.com/cognipilot">GitHub</a>
                </div>
            </div>
            <div class="footer-bottom">
                <p>&copy; 2024-2025 CogniPilot Foundation. Credentials issued as OpenBadges 3.0.</p>
            </div>
        </div>
    </footer>
</body>
</html>'''

    with open(output_path, 'w') as f:
        f.write(html)


def generate_credential_page(
    credential: dict,
    output_path: Path,
    badge_image_url: str,
    wallet_slug: str
) -> None:
    """Generate an individual credential page for LinkedIn sharing."""

    issuer = credential.get('issuer', {})
    issuer_name = issuer.get('name', 'Unknown') if isinstance(issuer, dict) else str(issuer)
    issuer_url = issuer.get('url', '#') if isinstance(issuer, dict) else '#'

    subject = credential.get('credentialSubject', {})
    recipient_name = subject.get('name', 'Recipient')
    achievement = subject.get('achievement', {})
    name = achievement.get('name') or credential.get('name', 'Achievement')
    description = achievement.get('description', '')
    achievement_type = achievement.get('achievementType', '')
    # Strip namespace prefix for display (e.g., "ext:Role" -> "Role")
    if ':' in achievement_type:
        achievement_type = achievement_type.split(':')[-1]

    valid_from = credential.get('validFrom', '')
    valid_until = credential.get('validUntil', '')
    issue_date = valid_from[:10] if valid_from else 'Unknown'
    expiry_date = valid_until[:10] if valid_until else None

    cred_id = credential.get('id', '')
    credential_page_url = cred_id
    # Extract achievement_id from credential ID URL (last path segment)
    achievement_id = cred_id.split('/')[-1] if cred_id else ''

    # Use SVG for badge display on page (PNG used for LinkedIn og:image)
    badge_embed = f'<div class="badge-image"><img src="badge.svg" alt="{name}"></div>'

    linkedin_url = generate_linkedin_url(credential, credential_page_url)
    wallet_url = f"/profile/{wallet_slug}/wallet"

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <link rel="icon" type="image/png" href="/images/favicon.png">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{name} - {recipient_name} | CogniPilot</title>
    <meta property="og:title" content="{name}">
    <meta property="og:description" content="{recipient_name} earned {name} from {issuer_name}">
    <meta property="og:type" content="website">
    <meta property="og:image" content="{badge_image_url}">
    <meta property="og:image:type" content="image/png">
    <meta property="og:image:width" content="1200">
    <meta property="og:image:height" content="627">
    <link rel="stylesheet" href="/css/style.css">
    <style>
        .credential-container {{
            max-width: 600px;
            margin: 0 auto;
            padding: 48px 24px;
        }}
        .credential-card {{
            background: var(--color-bg-card);
            border-radius: var(--radius-xl);
            overflow: hidden;
            box-shadow: var(--shadow-lg);
            border: 1px solid var(--color-border);
        }}
        .badge-section {{
            background: linear-gradient(135deg, var(--color-bg-darker) 0%, var(--color-bg-card) 100%);
            padding: 48px;
            text-align: center;
        }}
        .badge-image img {{
            max-width: 400px;
            height: auto;
        }}
        .credential-details {{
            padding: 32px;
        }}
        .verified-status {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: rgba(76, 175, 80, 0.15);
            color: #4CAF50;
            padding: 8px 16px;
            border-radius: 20px;
            font-size: 0.875rem;
            font-weight: 500;
            margin-bottom: 16px;
        }}
        .verified-status svg {{
            width: 18px;
            height: 18px;
        }}
        .credential-title {{
            font-size: 1.75rem;
            margin-bottom: 8px;
        }}
        .credential-recipient {{
            color: var(--color-primary);
            font-size: 1.25rem;
            margin-bottom: 16px;
        }}
        .credential-issuer {{
            color: var(--color-text-secondary);
            font-size: 0.9375rem;
            margin-bottom: 20px;
        }}
        .credential-issuer a {{
            color: var(--color-primary);
        }}
        .credential-description {{
            color: var(--color-text-secondary);
            line-height: 1.7;
            margin-bottom: 24px;
        }}
        .credential-meta {{
            border-top: 1px solid var(--color-border);
            padding-top: 20px;
            margin-top: 20px;
        }}
        .meta-row {{
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            font-size: 0.875rem;
        }}
        .meta-label {{
            color: var(--color-text-muted);
        }}
        .meta-value {{
            color: var(--color-text);
        }}
        .action-buttons {{
            display: flex;
            gap: 12px;
            flex-wrap: wrap;
            margin-top: 24px;
        }}
        .btn-linkedin {{
            background: #0077B5;
            color: white;
        }}
        .btn-linkedin:hover {{
            background: #005885;
            color: white;
        }}
        .download-section {{
            border-top: 1px solid var(--color-border);
            padding-top: 20px;
            margin-top: 20px;
        }}
        .download-section h3 {{
            font-size: 0.875rem;
            color: var(--color-text-muted);
            margin-bottom: 12px;
            font-weight: 500;
        }}
        .download-buttons {{
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
        }}
        .btn-download {{
            background: var(--color-bg-darker);
            color: var(--color-text);
            border: 1px solid var(--color-border);
            padding: 8px 16px;
            font-size: 0.875rem;
        }}
        .btn-download:hover {{
            background: var(--color-bg-card);
            border-color: var(--color-primary);
            color: var(--color-primary);
        }}
        .btn-download svg {{
            width: 16px;
            height: 16px;
            margin-right: 6px;
        }}
        .back-link {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            color: var(--color-text-secondary);
            margin-bottom: 24px;
            font-size: 0.875rem;
        }}
        .back-link:hover {{
            color: var(--color-primary);
        }}
    </style>
</head>
<body>
    <nav class="navbar">
        <div class="container nav-container">
            <a href="/" class="nav-brand">
                <img src="/images/cognipilot-logo.png" alt="CogniPilot" class="nav-logo">
                <span>Credentials</span>
            </a>
            <div class="nav-links">
                <a href="/" class="nav-link">Home</a>
                <a href="/issuer" class="nav-link">Issuer</a>
                <a href="/verify" class="nav-link">Verify</a>
            </div>
        </div>
    </nav>

    <main class="credential-container">
        <a href="{wallet_url}" class="back-link">
            <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                <path d="M19 12H5M12 19l-7-7 7-7"/>
            </svg>
            Back to wallet
        </a>

        <div class="credential-card">
            <div class="badge-section">
                {badge_embed}
            </div>
            <div class="credential-details">
                <div class="verified-status">
                    <svg fill="currentColor" viewBox="0 0 20 20">
                        <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/>
                    </svg>
                    Verified Credential
                </div>

                <h1 class="credential-title">{name}</h1>
                <div class="credential-recipient">Awarded to {recipient_name}</div>
                <div class="credential-issuer">Issued by <a href="{issuer_url}" target="_blank">{issuer_name}</a></div>
                <div class="credential-description">{description}</div>

                <div class="action-buttons">
                    <a href="{linkedin_url}" target="_blank" class="btn btn-linkedin">
                        <svg width="20" height="20" fill="currentColor" viewBox="0 0 24 24">
                            <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433c-1.144 0-2.063-.926-2.063-2.065 0-1.138.92-2.063 2.063-2.063 1.14 0 2.064.925 2.064 2.063 0 1.139-.925 2.065-2.064 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/>
                        </svg>
                        Add to LinkedIn
                    </a>
                    <a href="/verify#{wallet_slug}/{achievement_id}" class="btn btn-secondary">
                        Verify
                    </a>
                </div>

                <div class="credential-meta">
                    <div class="meta-row">
                        <span class="meta-label">Type</span>
                        <span class="meta-value">{achievement_type}</span>
                    </div>
                    <div class="meta-row">
                        <span class="meta-label">Issued</span>
                        <span class="meta-value">{issue_date}</span>
                    </div>
                    {'<div class="meta-row"><span class="meta-label">Expires</span><span class="meta-value">' + expiry_date + '</span></div>' if expiry_date else ''}
                </div>

                <div class="download-section">
                    <h3>Download Credential</h3>
                    <div class="download-buttons">
                        <a href="credential.json" download class="btn btn-download">
                            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z"/>
                            </svg>
                            JSON
                        </a>
                        <a href="badge.png" download class="btn btn-download">
                            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"/>
                            </svg>
                            PNG
                        </a>
                        <a href="badge.svg" download class="btn btn-download">
                            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z"/>
                            </svg>
                            SVG
                        </a>
                    </div>
                </div>
            </div>
        </div>
    </main>

    <footer class="footer">
        <div class="container">
            <div class="footer-content">
                <div class="footer-brand">
                    <img src="/images/cognipilot-logo.png" alt="CogniPilot" class="footer-logo">
                    <span>CogniPilot Credentials</span>
                </div>
                <div class="footer-links">
                    <a href="https://cognipilot.org">CogniPilot.org</a>
                    <a href="https://github.com/cognipilot">GitHub</a>
                </div>
            </div>
            <div class="footer-bottom">
                <p>&copy; 2024-2025 CogniPilot Foundation. Credentials issued as OpenBadges 3.0.</p>
            </div>
        </div>
    </footer>

    <script>
        // Embedded credential data for verification
        const credential = {json.dumps(credential)};
    </script>
</body>
</html>'''

    with open(output_path, 'w') as f:
        f.write(html)


def process_rename_wallet(request: dict, registry: dict) -> dict:
    """Process a wallet rename request."""
    email = request.get('recipient_email')
    new_slug = request.get('new_wallet_slug')
    new_display_name = request.get('recipient_name')

    if not email or not new_slug:
        print("Error: rename_wallet requires recipient_email and new_wallet_slug")
        return None

    normalized_email = normalize_email(email)
    old_slug = get_wallet_slug_for_email(normalized_email, registry)

    if not old_slug:
        print(f"Error: No wallet found for email {email}")
        return None

    new_slug = name_to_slug(new_slug)

    if old_slug == new_slug:
        print(f"Wallet slug is already '{new_slug}'")
        return None

    # Check if new slug already exists (and it's not the same wallet)
    if new_slug in registry["wallets"]:
        print(f"Error: Wallet slug '{new_slug}' already exists")
        return None

    # Rename in registry
    if not rename_wallet(old_slug, new_slug, registry, new_display_name):
        print("Error: Failed to rename wallet in registry")
        return None

    # Move profile directory
    old_profile_dir = PROFILES_DIR / old_slug
    new_profile_dir = PROFILES_DIR / new_slug

    if old_profile_dir.exists():
        print(f"Moving profile directory: {old_slug} -> {new_slug}")
        shutil.move(str(old_profile_dir), str(new_profile_dir))

        # Update credential IDs in all credential.json files
        for cred_dir in new_profile_dir.iterdir():
            if cred_dir.is_dir() and cred_dir.name != 'wallet':
                cred_file = cred_dir / 'credential.json'
                if cred_file.exists():
                    with open(cred_file) as f:
                        cred = json.load(f)

                    # Update credential ID
                    old_id = cred.get('id', '')
                    if old_slug in old_id:
                        cred['id'] = old_id.replace(f'/profile/{old_slug}/', f'/profile/{new_slug}/')

                    with open(cred_file, 'w') as f:
                        json.dump(cred, f, indent=2)

    save_wallet_registry(registry)

    print(f"Renamed wallet: {old_slug} -> {new_slug}")
    print(f"New wallet URL: {BASE_URL}/profile/{new_slug}/wallet")

    return {
        'old_slug': old_slug,
        'new_slug': new_slug,
        'wallet_url': f"{BASE_URL}/profile/{new_slug}/wallet"
    }


def process_request(request_file: Path, key_path: Path, dry_run: bool = False) -> dict:
    """Process a single credential request file."""

    with open(request_file) as f:
        request = json.load(f)

    request_type = request.get('request_type', 'issue')
    registry = load_wallet_registry()

    # Handle wallet rename requests
    if request_type == 'rename_wallet':
        if dry_run:
            print(f"Would rename wallet for {request.get('recipient_email')} to {request.get('new_wallet_slug')}")
            return None

        result = process_rename_wallet(request, registry)
        if result:
            request['status'] = 'renamed'
            request['processed_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            request['old_wallet_slug'] = result['old_slug']
            request['wallet_slug'] = result['new_slug']
            request['wallet_url'] = result['wallet_url']

            with open(request_file, 'w') as f:
                json.dump(request, f, indent=2)

            return {'wallet_slug': result['new_slug'], 'request': request}
        return None

    # Check if already processed (only for issue requests)
    if request_type == 'issue' and request.get('status') == 'issued':
        print(f"Skipping already issued: {request_file.name}")
        return None

    # Load achievement
    achievement_id = request['achievement']
    achievement_path = ACHIEVEMENTS_DIR / f"{achievement_id}.json"

    if not achievement_path.exists():
        print(f"Error: Achievement not found: {achievement_id}")
        return None

    with open(achievement_path) as f:
        achievement = json.load(f)

    # Get recipient info
    recipient_name = request['recipient_name']
    recipient_email = request['recipient_email']
    normalized_email = normalize_email(recipient_email)

    # Determine wallet slug
    existing_slug = get_wallet_slug_for_email(normalized_email, registry)

    if existing_slug:
        # Use existing wallet
        wallet_slug = existing_slug
        print(f"Using existing wallet: {wallet_slug}")
    else:
        # Create new wallet from recipient name
        wallet_slug = name_to_slug(recipient_name)

        # Ensure unique slug
        base_slug = wallet_slug
        counter = 1
        while wallet_slug in registry["wallets"]:
            wallet_slug = f"{base_slug}-{counter}"
            counter += 1

        print(f"Creating new wallet: {wallet_slug}")

    # Handle update requests
    old_wallet_slug = None
    old_credential_dir = None

    if request_type == 'update':
        old_email = request.get('old_email')
        if old_email:
            old_wallet_slug, old_credential_dir = find_existing_credential(
                achievement_id, old_email
            )
            if not old_credential_dir:
                print(f"Error: Cannot find existing credential for {old_email} with {achievement_id}")
                return None
            print(f"Found existing credential at: {old_credential_dir}")

    # Create credential
    credential = create_credential(
        achievement=achievement,
        recipient_email=recipient_email,
        recipient_name=recipient_name,
        wallet_slug=wallet_slug,
        achievement_id=achievement_id,
        valid_from=request.get('valid_from'),
        valid_until=request.get('valid_until')
    )

    if dry_run:
        print(f"Would process ({request_type}): {recipient_name} <{recipient_email}> - {achievement.get('name')}")
        print(f"  Wallet: {wallet_slug}")
        if request_type == 'update' and old_wallet_slug and old_wallet_slug != wallet_slug:
            print(f"  Would move from wallet '{old_wallet_slug}' to '{wallet_slug}'")
        return {'request': request, 'credential': credential}

    # Register wallet/email mapping
    register_wallet(wallet_slug, recipient_email, recipient_name, registry)
    save_wallet_registry(registry)

    # Load signing key
    signing_key, verification_method = load_private_key(key_path)

    # Sign credential
    signed_credential = sign_credential(credential, signing_key, verification_method)

    # Handle wallet move for updates
    if request_type == 'update' and old_credential_dir and old_wallet_slug != wallet_slug:
        print(f"Moving credential from wallet '{old_wallet_slug}' to '{wallet_slug}'")
        shutil.rmtree(old_credential_dir)

        # Check if old wallet is now empty
        old_profile_dir = PROFILES_DIR / old_wallet_slug
        if old_profile_dir.exists():
            remaining_creds = [d for d in old_profile_dir.iterdir()
                             if d.is_dir() and d.name != 'wallet']
            if not remaining_creds:
                print(f"Removing empty wallet: {old_profile_dir}")
                shutil.rmtree(old_profile_dir)

    # Create profile directory structure
    profile_dir = PROFILES_DIR / wallet_slug
    credential_dir = profile_dir / achievement_id
    credential_dir.mkdir(parents=True, exist_ok=True)

    # Save credential JSON
    public_credential_path = credential_dir / "credential.json"
    with open(public_credential_path, 'w') as f:
        json.dump(signed_credential, f, indent=2)
    print(f"Saved public credential: {public_credential_path}")

    # Find and bake badge SVG
    image_info = achievement.get('image', {})
    image_url = image_info.get('id', '') if isinstance(image_info, dict) else str(image_info)
    baked_path = None
    personalized_png_path = None

    if image_url:
        svg_filename = image_url.split('/')[-1]
        svg_path = BADGES_DIR / svg_filename

        if svg_path.exists():
            with open(svg_path) as f:
                svg_content = f.read()

            # Add earner name to the badge
            svg_with_name = add_earner_name(svg_content, recipient_name)
            print(f"Added earner name to badge: {recipient_name}")

            # Bake credential into SVG
            baked_svg = bake_svg(svg_with_name, signed_credential)

            # Save baked SVG to profile directory
            profile_svg_path = credential_dir / "badge.svg"
            with open(profile_svg_path, 'w') as f:
                f.write(baked_svg)
            print(f"Saved baked SVG: {profile_svg_path}")

            # Generate PNG with baked credential (OB 3.0 format)
            profile_png_path = credential_dir / "badge.png"
            try:
                svg_to_png(baked_svg, profile_png_path, width=500,
                          credential=signed_credential)
                print(f"Saved baked PNG: {profile_png_path}")
            except RuntimeError as e:
                print(f"Warning: Could not generate PNG: {e}")
        else:
            print(f"Warning: Badge SVG not found: {svg_path}")

    # Credential page URL
    credential_page_url = f"{BASE_URL}/profile/{wallet_slug}/{achievement_id}"

    # Get badge PNG URL for og:image
    badge_image_url = None
    if (credential_dir / "badge.png").exists():
        badge_image_url = f"{BASE_URL}/profile/{wallet_slug}/{achievement_id}/badge.png"
    elif image_url:
        # Fallback to generic badge
        badge_png_filename = image_url.split('/')[-1].replace('.svg', '.png')
        badge_image_url = f"{BASE_URL}/images/badges/{badge_png_filename}"

    # Generate individual credential page
    credential_index_path = credential_dir / "index.html"
    generate_credential_page(
        signed_credential,
        output_path=credential_index_path,
        badge_image_url=badge_image_url,
        wallet_slug=wallet_slug
    )
    print(f"Saved credential page: {credential_index_path}")

    # Generate LinkedIn URL
    linkedin_url = generate_linkedin_url(signed_credential, credential_page_url)

    # Update request status
    request['status'] = 'issued' if request_type == 'issue' else 'updated'
    request['processed_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    request['wallet_slug'] = wallet_slug
    request['credential_url'] = credential_page_url
    request['wallet_url'] = f"{BASE_URL}/profile/{wallet_slug}/wallet"
    request['linkedin_url'] = linkedin_url

    with open(request_file, 'w') as f:
        json.dump(request, f, indent=2)

    print(f"\nCredential URL: {credential_page_url}")
    print(f"Wallet URL: {BASE_URL}/profile/{wallet_slug}/wallet")
    print(f"LinkedIn share URL:\n{linkedin_url}\n")

    return {
        'request': request,
        'credential_url': credential_page_url,
        'linkedin_url': linkedin_url,
        'wallet_slug': wallet_slug,
        'signed_credential': signed_credential,
        'old_wallet_slug': old_wallet_slug if request_type == 'update' else None
    }


def update_wallet_pages(results: list) -> None:
    """Update wallet pages for all recipients with processed credentials."""

    registry = load_wallet_registry()

    # Collect all wallet slugs that need updates
    affected_slugs = set()
    for result in results:
        if result:
            affected_slugs.add(result['wallet_slug'])
            if result.get('old_wallet_slug'):
                affected_slugs.add(result['old_wallet_slug'])

    # Build recipient data from profile directories
    recipients = {}

    if PROFILES_DIR.exists():
        for profile_path in PROFILES_DIR.iterdir():
            if not profile_path.is_dir():
                continue

            wallet_slug = profile_path.name

            # Skip if not affected and we have specific results
            if results and wallet_slug not in affected_slugs:
                continue

            # Get display name from registry or default
            wallet_info = registry.get("wallets", {}).get(wallet_slug, {})
            display_name = wallet_info.get("display_name", wallet_slug.replace('-', ' ').title())

            recipients[wallet_slug] = {
                'name': display_name,
                'credentials': []
            }

            # Load all credentials in this profile
            for cred_dir in profile_path.iterdir():
                if cred_dir.is_dir() and cred_dir.name != 'wallet':
                    cred_file = cred_dir / 'credential.json'
                    if cred_file.exists():
                        with open(cred_file) as f:
                            cred = json.load(f)
                        recipients[wallet_slug]['credentials'].append(cred)
                        # Update name from credential if registry doesn't have it
                        if not wallet_info.get("display_name"):
                            subject = cred.get('credentialSubject', {})
                            if subject.get('name'):
                                recipients[wallet_slug]['name'] = subject['name']

    # Generate wallet page for each recipient
    for wallet_slug, data in recipients.items():
        if not data['credentials']:
            continue

        wallet_dir = PROFILES_DIR / wallet_slug / 'wallet'
        wallet_dir.mkdir(parents=True, exist_ok=True)

        wallet_path = wallet_dir / 'index.html'
        generate_wallet_page(
            wallet_slug=wallet_slug,
            recipient_name=data['name'],
            credentials=data['credentials'],
            output_path=wallet_path
        )
        print(f"Updated wallet page: {wallet_path}")
        print(f"  Wallet URL: {BASE_URL}/profile/{wallet_slug}/wallet")


def regenerate_all_credential_pages():
    """Regenerate HTML pages for all existing credentials from their credential.json files."""
    print("Regenerating all credential pages...")

    # Find all credential.json files
    credential_files = list(PROFILES_DIR.glob('*/*/credential.json'))

    for cred_file in credential_files:
        try:
            with open(cred_file) as f:
                credential = json.load(f)

            cred_dir = cred_file.parent
            output_path = cred_dir / 'index.html'

            # Extract wallet_slug from path (profile/<wallet_slug>/<cred_slug>/credential.json)
            wallet_slug = cred_dir.parent.name

            # Extract badge image URL from credential
            subject = credential.get('credentialSubject', {})
            achievement = subject.get('achievement', {})
            image_info = achievement.get('image', {})
            badge_image_url = image_info.get('id', '') if isinstance(image_info, dict) else str(image_info)

            generate_credential_page(credential, output_path, badge_image_url, wallet_slug)
            print(f"Regenerated: {output_path}")

        except Exception as e:
            print(f"Error regenerating {cred_file}: {e}")

    print(f"\nRegenerated {len(credential_files)} credential page(s)")


def main():
    parser = argparse.ArgumentParser(
        description='Process credential requests and generate badges'
    )
    parser.add_argument(
        '--key', '-k',
        type=Path,
        default=KEYS_DIR / 'key-1-private.json',
        help='Path to private key JSON file'
    )
    parser.add_argument(
        '--request', '-r',
        type=Path,
        help='Process a specific request file (default: all pending)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be processed without generating files'
    )
    parser.add_argument(
        '--update-wallets',
        action='store_true',
        help='Update wallet pages for all existing profiles'
    )
    parser.add_argument(
        '--regenerate-pages',
        action='store_true',
        help='Regenerate all credential and wallet HTML pages from existing credential.json files'
    )
    args = parser.parse_args()

    if args.regenerate_pages:
        regenerate_all_credential_pages()
        update_wallet_pages([])
        return

    if args.update_wallets:
        update_wallet_pages([])
        return

    if args.request:
        request_files = [args.request]
    else:
        request_files = sorted([
            f for f in REQUESTS_DIR.glob('*.json')
            if not f.name.startswith('_')
        ])

    if not request_files:
        print("No request files found")
        return

    results = []
    for request_file in request_files:
        print(f"\n{'=' * 60}")
        print(f"Processing: {request_file.name}")
        print('=' * 60)

        result = process_request(request_file, args.key, args.dry_run)
        if result:
            results.append(result)

    if results and not args.dry_run:
        print(f"\n{'=' * 60}")
        print("Updating wallet pages...")
        print('=' * 60)
        update_wallet_pages(results)

    print(f"\n{'=' * 60}")
    print(f"Processed {len(results)} credential(s)")
    print('=' * 60)


if __name__ == '__main__':
    main()
