#!/usr/bin/env python3
"""
Update the badge-request issue template with current/upcoming year badges.

Filters year-based badges to only show:
- Badges for the current year
- Badges for previous year if within 30 days of year start
- Badges for next year if within 30 days of year end

Non-year badges (maintainer, contributor, collaborator) are always shown.
"""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path


SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent
ACHIEVEMENTS_DIR = REPO_ROOT / 'achievements'
TEMPLATE_PATH = REPO_ROOT / '.github' / 'ISSUE_TEMPLATE' / 'badge-request.yml'


def get_relevant_years() -> set:
    """Get the set of years that should be shown in the template."""
    today = datetime.now()
    years = {today.year}

    # If within 30 days of year start, also include previous year
    year_start = datetime(today.year, 1, 1)
    if (today - year_start).days <= 30:
        years.add(today.year - 1)

    # If within 30 days of year end, also include next year
    year_end = datetime(today.year, 12, 31)
    if (year_end - today).days <= 30:
        years.add(today.year + 1)

    return years


def parse_year_from_id(achievement_id: str) -> int | None:
    """Extract year from achievement ID if present."""
    match = re.search(r'-(\d{4})$', achievement_id)
    if match:
        return int(match.group(1))
    return None


def load_achievements() -> list:
    """Load all achievements and return filtered list for template."""
    achievements = []

    for path in sorted(ACHIEVEMENTS_DIR.glob('*.json')):
        with open(path) as f:
            data = json.load(f)

        achievement_id = path.stem
        name = data.get('name', achievement_id)
        year = parse_year_from_id(achievement_id)

        achievements.append({
            'id': achievement_id,
            'name': name,
            'year': year
        })

    return achievements


def filter_achievements(achievements: list) -> list:
    """Filter achievements based on year relevance."""
    relevant_years = get_relevant_years()
    filtered = []

    # First add non-year badges (sorted alphabetically)
    non_year = [a for a in achievements if a['year'] is None]
    non_year.sort(key=lambda x: x['name'])
    filtered.extend(non_year)

    # Then add year-based badges for relevant years
    year_badges = [a for a in achievements if a['year'] in relevant_years]
    # Sort by: year (ascending), then name
    year_badges.sort(key=lambda x: (x['year'], x['name']))
    filtered.extend(year_badges)

    return filtered


def generate_options(achievements: list) -> list:
    """Generate the YAML options list."""
    options = []
    for a in achievements:
        option = f'        - "{a["name"]} ({a["id"]})"'
        options.append(option)
    return options


def update_template(options: list) -> bool:
    """Update the badge-request template with new options."""
    with open(TEMPLATE_PATH) as f:
        content = f.read()

    # Find the options section and replace it
    # Match from "options:" to the next field (validations:)
    pattern = r'(      options:\n)(.*?)(    validations:)'

    options_block = '        # AUTO-GENERATED - Do not edit manually\n'
    options_block += '        # Updated by update-issue-template workflow\n'
    options_block += '\n'.join(options) + '\n'

    new_content = re.sub(
        pattern,
        r'\1' + options_block + r'\3',
        content,
        flags=re.DOTALL
    )

    if new_content == content:
        print("No changes needed")
        return False

    with open(TEMPLATE_PATH, 'w') as f:
        f.write(new_content)

    print(f"Updated template with {len(options)} badge options")
    return True


def main():
    print(f"Relevant years: {get_relevant_years()}")

    achievements = load_achievements()
    print(f"Found {len(achievements)} total achievements")

    filtered = filter_achievements(achievements)
    print(f"Filtered to {len(filtered)} relevant achievements")

    for a in filtered:
        year_str = f" ({a['year']})" if a['year'] else ""
        print(f"  - {a['name']}{year_str}")

    options = generate_options(filtered)
    changed = update_template(options)

    return 0 if not changed else 0


if __name__ == '__main__':
    exit(main())
