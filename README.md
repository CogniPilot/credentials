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
- `badge.svg` - Baked SVG badge with earner name
- `badge.png` - PNG badge with embedded credential URL
- `index.html` - Credential page for sharing

## Verification

Verify credentials at: https://credentials.cognipilot.org/verify
