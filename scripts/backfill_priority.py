"""One-off: add `Priority: 3` to any vault task note missing the field.
Run: uv run python scripts/backfill_priority.py [--dry-run]
"""
import sys

import yaml

from griot.config import load_config
from griot.tasks.model import split_frontmatter
from griot.tasks.writer import set_field


def main() -> None:
    dry = "--dry-run" in sys.argv
    tasks = load_config().tasks_path
    changed = []
    for path in sorted(tasks.glob("*.md")):
        split = split_frontmatter(path.read_text())
        if split is None:
            print(f"skip (no frontmatter): {path.name}")
            continue
        try:
            meta = yaml.safe_load("\n".join(split[0])) or {}
        except yaml.YAMLError:
            print(f"skip (bad yaml): {path.name}")
            continue
        if "Priority" in meta:
            continue
        if not dry:
            set_field(path, "Priority", "3")
        changed.append(path.name)
    print(f"{'would update' if dry else 'updated'} {len(changed)} notes")
    for name in changed:
        print(f"  {name}")


if __name__ == "__main__":
    main()
