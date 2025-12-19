# CogniPilot Badges

OpenBadges 3.0 digital credentials for the CogniPilot community.

## Issuing a Credential

1. Create a request file in `requests/`:

```json
{
  "recipient_name": "Jane Doe",
  "recipient_email": "jane@example.com",
  "achievement": "tsc-member-2026",
  "valid_from": "2026-01-01T00:00:00Z",
  "valid_until": "2026-12-31T23:59:59Z",
  "status": "pending"
}
```

2. Commit and push - GitHub Actions will automatically process the request and generate:
   - Signed credential JSON
   - Baked SVG badge
   - HTML share page with LinkedIn button
   - QR code for verification

3. Share outputs from `output/<name>-<achievement>/` with the recipient.

## Verification

Verify credentials at: https://credentials.cognipilot.org/verify
