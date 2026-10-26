#!/usr/bin/env python3
"""Install the reviewed local Quorum skill without modifying host settings."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

REPOSITORY = "https://github.com/maksimryabkin/ai-skills"
RECORD = ".quorum-install.json"
SOURCE = Path(__file__).resolve().parents[1] / "skills" / "quorum"
TARGETS = {"codex": Path(".agents/skills/quorum"), "claude": Path(".claude/skills/quorum")}


def inventory(directory: Path) -> dict[str, str]:
    result = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Symlink inside skill: {path}")
        if path.is_file() and path.relative_to(directory).as_posix() != RECORD:
            result[path.relative_to(directory).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def validate_destination(root: Path, destination: Path) -> None:
    current = root
    for part in destination.relative_to(root).parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f"Refusing to follow installation symlink: {current}")
        if current != destination and current.exists() and not current.is_dir():
            raise ValueError(f"Parent is not a directory: {current}")


def plan(root: Path, destination: Path, files: dict[str, str], update: bool) -> str:
    validate_destination(root, destination)
    if not destination.exists():
        return "installed"
    if not destination.is_dir():
        raise ValueError(f"Destination is not a directory: {destination}")
    marker = destination / RECORD
    if marker.is_symlink() or not marker.is_file():
        raise ValueError(f"Existing skill has no Quorum installation record: {destination}")
    try:
        previous = json.loads(marker.read_text(encoding="utf-8"))
    except (ValueError, OSError) as error:
        raise ValueError(f"Unreadable installation record: {destination}") from error
    if not isinstance(previous, dict) or previous.get("repository") != REPOSITORY:
        raise ValueError(f"Existing skill belongs to another source: {destination}")
    current = inventory(destination)
    if current != previous.get("files"):
        raise ValueError(f"Skill was changed locally; review changes before updating: {destination}")
    if current == files:
        return "unchanged"
    if not update:
        raise ValueError(f"A different Quorum version exists; use --update: {destination}")
    return "updated"


def install(root: Path, target: str, update: bool = False) -> list[dict[str, str]]:
    root = root.expanduser().resolve()
    files = inventory(SOURCE)
    if "SKILL.md" not in files or not files:
        raise ValueError("Quorum source is incomplete")
    names = list(TARGETS) if target == "both" else [target]
    destinations = [(name, root / TARGETS[name]) for name in names]
    # Validate every requested host before making any installation changes
    actions = [(name, dest, plan(root, dest, files, update)) for name, dest in destinations]
    receipt = []
    for name, destination, action in actions:
        if action != "unchanged":
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=".quorum-stage-", dir=destination.parent) as temporary:
                staging_root = Path(temporary)
                staged = staging_root / "new"
                backup = staging_root / "previous"
                shutil.copytree(SOURCE, staged)
                (staged / RECORD).write_text(
                    json.dumps({"repository": REPOSITORY, "files": files}, indent=2) + "\n",
                    encoding="utf-8",
                )
                if inventory(staged) != files:
                    raise ValueError("Source changed during staging; retry from reviewed source")
                # Recheck for changed local files immediately before replacement
                actual = plan(root, destination, files, update)
                if actual != action:
                    raise ValueError(f"Destination changed during installation: {destination}")
                if action == "updated":
                    os.replace(destination, backup)
                try:
                    os.replace(staged, destination)
                except OSError:
                    if backup.exists():
                        os.replace(backup, destination)
                    raise
                if inventory(destination) != files:
                    raise ValueError(f"Installed files did not verify: {destination}")
        receipt.append({"target": name, "path": str(destination), "status": action})
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=[*TARGETS, "both"], required=True)
    parser.add_argument("--scope", choices=["user", "project"], default="user")
    parser.add_argument("--project-dir", type=Path)
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args()
    if args.scope == "project" and args.project_dir is None:
        parser.error("--scope project requires --project-dir")
    if args.scope == "user" and args.project_dir is not None:
        parser.error("--project-dir requires --scope project")
    root = args.project_dir if args.scope == "project" else Path.home()
    try:
        receipt = install(root, args.target, args.update)
    except (ValueError, OSError) as error:
        parser.exit(1, f"Installation stopped: {error}\n")
    print(json.dumps({"ok": True, "installations": receipt}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
