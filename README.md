# CogniPilot Credentials

OpenBadges 3.0 digital credentials for the CogniPilot community.

## Issuing a Credential

### Via GitHub Issue (Recommended)

1. [Create a new badge request issue](../../issues/new?template=badge-request.yml)
2. Fill out the form with recipient details and badge type
3. A member of the [@CogniPilot/credentials](https://github.com/orgs/CogniPilot/teams/credentials) team adds the `issue-badge` label
4. The workflow automatically:
   - Creates the signed credential
   - Generates baked SVG and PNG badges
   - Creates the credential page
   - Comments on the issue with links
   - Closes the issue

### Manual Method

1. Create a request file in `requests/`:

```json
{
  "recipient_name": "Jane Doe",
  "recipient_email": "jane@example.com",
  "achievement": "tsc-member-2026",
  "valid_from": "2026-01-01T00:00:00Z",
  "status": "pending"
}
```

2. Run `python scripts/process_requests.py` or commit and push to trigger the GitHub Actions workflow

Generated files are saved to `docs/profile/<wallet-slug>/<achievement-id>/`:
- `credential.json` - Signed verifiable credential
- `badge.svg` - Baked SVG badge with earner name and embedded credential
- `badge.png` - PNG badge with embedded credential metadata
- `index.html` - Credential page for sharing

## Updating Credentials

### Via GitHub Issue (Recommended)

1. [Create an update request issue](../../issues/new?template=update-credential.yml)
2. Fill out the form with your current email and requested changes
3. A maintainer will review and process your request

**Note:** If you have credentials in multiple wallets (e.g., from using different email addresses), updating to an email that already has a wallet will consolidate/merge your credentials into that existing wallet.

### Manual Method

Create an update request file in `requests/`:

```json
{
  "request_type": "update",
  "old_email": "old-email@example.com",
  "recipient_name": "Jane Doe",
  "recipient_email": "new-email@example.com",
  "achievement": "achievement-id",
  "valid_from": "2026-01-01T00:00:00Z",
  "valid_until": "2026-12-31T23:59:59Z"
}
```

## Renaming Wallet Slug

To change your profile URL slug, create a rename request:

```json
{
  "request_type": "rename_wallet",
  "recipient_email": "email@example.com",
  "recipient_name": "Display Name",
  "new_wallet_slug": "new-slug-name"
}
```

## Removing Credentials

### Via GitHub Issue (Recommended)

1. [Create a removal request issue](../../issues/new?template=remove-credential.yml)
2. Choose whether to remove specific credentials or your entire profile
3. Confirm the removal is intentional
4. A maintainer will review and process your request

### Manual Method

Create a removal request file in `requests/`:

```json
{
  "request_type": "remove",
  "recipient_email": "email@example.com",
  "remove_profile": false,
  "achievements": ["achievement-id-1", "achievement-id-2"]
}
```

Set `remove_profile` to `true` to remove your entire wallet and all credentials. Otherwise, list specific achievement IDs to remove.

## Verification

Verify credentials at: https://credentials.cognipilot.org/verify
