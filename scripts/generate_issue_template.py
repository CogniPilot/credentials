#!/usr/bin/env python3
"""
Generate GitHub issue template from available achievements.

This script reads all achievement JSON files and generates a GitHub issue
form template with a dropdown containing all available badge types.
"""

import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent
ACHIEVEMENTS_DIR = REPO_ROOT / 'achievements'
TEMPLATE_PATH = REPO_ROOT / '.github' / 'ISSUE_TEMPLATE' / 'badge-request.yml'


def main():
    # Load all achievements
    achievements = []
    for achievement_file in sorted(ACHIEVEMENTS_DIR.glob('*.json')):
        with open(achievement_file) as f:
            data = json.load(f)
        achievements.append({
            'id': achievement_file.stem,
            'name': data.get('name', achievement_file.stem)
        })

    # Build dropdown options
    options = '\n'.join(f'        - "{a["name"]} ({a["id"]})"' for a in achievements)

    template = f'''name: Badge Request
description: Request a CogniPilot credential badge
title: "[Badge Request] "
labels: ["badge-request"]
body:
  - type: markdown
    attributes:
      value: |
        ## Badge Request Form
        Fill out this form to request a CogniPilot credential badge.
        A maintainer will review and approve your request.

  - type: input
    id: recipient_name
    attributes:
      label: Recipient Name
      description: Full name of the badge recipient
      placeholder: "e.g., Jane Doe"
    validations:
      required: true

  - type: input
    id: recipient_email
    attributes:
      label: Recipient Email
      description: Email address for the badge recipient
      placeholder: "e.g., jane.doe@example.com"
    validations:
      required: true

  - type: dropdown
    id: achievement
    attributes:
      label: Badge Type
      description: Select the type of badge to issue
      options:
{options}
    validations:
      required: true

  - type: input
    id: valid_from
    attributes:
      label: Valid From Date (Optional)
      description: Start date for the credential (ISO format). Leave blank for today.
      placeholder: "e.g., 2025-01-01"
    validations:
      required: false

  - type: textarea
    id: justification
    attributes:
      label: Justification
      description: Brief explanation of why this badge should be issued
      placeholder: "Describe the recipient's contributions or role..."
    validations:
      required: true
'''

    # Write template
    TEMPLATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(TEMPLATE_PATH, 'w') as f:
        f.write(template)

    print(f"Generated issue template: {TEMPLATE_PATH}")
    print(f"Included {len(achievements)} achievements")


if __name__ == '__main__':
    main()
