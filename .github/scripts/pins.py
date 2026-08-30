#!/usr/bin/env python3
"""Keep the container images an app pins in sync with their upstream releases.

Each app in this repo is packaging only: the Dockerfile copies prebuilt upstream
images in rather than building from source, so "updating the app" means bumping a
tag in `<addon>/Dockerfile`, `<addon>/build.yaml`, the README, and the add-on
version in `<addon>/config.yaml`.

Dependabot cannot do that here — its Docker ecosystem only reads literal `FROM`
lines, and these Dockerfiles resolve their images through `ARG` (plus build.yaml,
which Dependabot doesn't know about at all). Hence this script.

    pins.py check              verify every pin in the repo is self-consistent
    pins.py bump --addon NAME  pull the newest tags and rewrite the pins

No third-party dependencies: it runs on a stock `ubuntu-latest` python3.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# The add-on base image. It pins libcrypto3/libssl3 to an exact version, so letting
# it fall behind the Alpine index breaks `apk add` for any package that needs the
# newer libraries — which is how the garage build broke at 1.3.6.
BASE_IMAGE = "hassio-addons/base"

# Apps whose pins are tracked. `images` must all publish the same tag (upstream
# builds and releases them together) and drive the add-on version; `track_base`
# additionally follows the base image, which only bumps the packaging revision.
TRACKED = {
    "garage": {
        "images": ["eigger/garage-api", "eigger/garage-web"],
        "release_url": "https://github.com/eigger/garage/releases/tag/v{version}",
        "track_base": True,
    },
}

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
TEXT_SUFFIXES = {".yaml", ".yml", ".md", ".sh", ".conf", ".json", ""}


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


# --------------------------------------------------------------------------- ghcr


def _ghcr_token(image: str) -> str:
    url = f"https://ghcr.io/token?scope=repository:{image}:pull&service=ghcr.io"
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.load(resp)["token"]


def ghcr_tags(image: str) -> list[str]:
    """Every tag of a public GHCR image. The registry paginates at 100 by default
    and signals more pages through a Link header, so a naive single GET silently
    reports a months-old tag as the newest one."""
    token = _ghcr_token(image)
    tags: list[str] = []
    path = f"/v2/{image}/tags/list?n=1000"
    while path:
        req = urllib.request.Request(
            f"https://ghcr.io{path}", headers={"Authorization": f"Bearer {token}"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            tags.extend(json.load(resp).get("tags") or [])
            link = resp.headers.get("Link", "")
        match = re.search(r'<([^>]+)>;\s*rel="next"', link)
        path = match.group(1) if match else ""
    return tags


def latest_version(image: str) -> str:
    versions = [t for t in ghcr_tags(image) if SEMVER.match(t)]
    if not versions:
        raise SystemExit(f"{image} publishes no semver tag")
    return max(versions, key=version_key)


def latest_common_version(images: list[str]) -> str:
    shared: set[str] | None = None
    for image in images:
        semver = {t for t in ghcr_tags(image) if SEMVER.match(t)}
        shared = semver if shared is None else (shared & semver)
    if not shared:
        raise SystemExit(f"no semver tag published by all of {', '.join(images)}")
    return max(shared, key=version_key)


# --------------------------------------------------------------------------- files


def addon_dirs() -> list[Path]:
    return sorted(
        p.parent
        for p in REPO_ROOT.glob("*/config.yaml")
        if not p.parent.name.startswith(".")
    )


def text_files(addon: Path) -> list[Path]:
    """Every readable text file of an app — icons and other binaries are skipped."""
    files = []
    for path in sorted(addon.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        files.append(path)
    return files


def pinned_tags(addon: Path, image: str) -> dict[Path, set[str]]:
    pattern = re.compile(rf"ghcr\.io/{re.escape(image)}:(\S+?)(?=[\s`'\"]|$)")
    found: dict[Path, set[str]] = {}
    for path in text_files(addon):
        tags = set(pattern.findall(path.read_text(encoding="utf-8")))
        if tags:
            found[path] = tags
    return found


def single_pin(addon: Path, images: list[str]) -> str:
    tags = {
        tag
        for image in images
        for tagset in pinned_tags(addon, image).values()
        for tag in tagset
    }
    if len(tags) != 1:
        raise SystemExit(f"{addon.name}: {images} disagree on a tag {sorted(tags)}")
    return tags.pop()


def repin(addon: Path, image: str, old: str, new: str) -> None:
    for path in pinned_tags(addon, image):
        text = path.read_text(encoding="utf-8")
        path.write_text(
            text.replace(f"ghcr.io/{image}:{old}", f"ghcr.io/{image}:{new}"),
            encoding="utf-8",
        )


def addon_version(addon: Path) -> str:
    text = (addon / "config.yaml").read_text(encoding="utf-8")
    match = re.search(r'^version:\s*"?([^"\n]+)"?\s*$', text, re.MULTILINE)
    if not match:
        raise SystemExit(f"{addon.name}/config.yaml has no version")
    return match.group(1).strip()


def set_addon_version(addon: Path, version: str) -> None:
    config = addon / "config.yaml"
    config.write_text(
        re.sub(
            r'^version:\s*"?[^"\n]+"?\s*$',
            f'version: "{version}"',
            config.read_text(encoding="utf-8"),
            count=1,
            flags=re.MULTILINE,
        ),
        encoding="utf-8",
    )


def next_revision(version: str) -> str:
    """An app's version is the upstream tag plus an optional packaging revision,
    so a base-image-only change goes 1.3.6 -> 1.3.6.1 -> 1.3.6.2."""
    parts = version.split(".")
    if len(parts) > 3:
        return ".".join(parts[:-1] + [str(int(parts[-1]) + 1)])
    return f"{version}.1"


# --------------------------------------------------------------------------- check


def cmd_check() -> int:
    problems: list[str] = []
    for addon in addon_dirs():
        tracked = TRACKED.get(addon.name, {})
        for image in list(tracked.get("images", [])) + [BASE_IMAGE]:
            per_file = pinned_tags(addon, image)
            tags = {tag for tagset in per_file.values() for tag in tagset}
            if len(tags) > 1:
                where = ", ".join(
                    f"{p.relative_to(REPO_ROOT)}={'/'.join(sorted(t))}"
                    for p, t in per_file.items()
                )
                problems.append(f"{addon.name}: {image} pinned to {sorted(tags)} ({where})")

        if not tracked:
            continue
        upstream = {
            tag
            for image in tracked["images"]
            for tagset in pinned_tags(addon, image).values()
            for tag in tagset
        }
        if len(upstream) != 1:
            problems.append(f"{addon.name}: images disagree on the upstream tag {sorted(upstream)}")
            continue
        pin = upstream.pop()
        version = addon_version(addon)
        if version != pin and not version.startswith(f"{pin}."):
            problems.append(
                f"{addon.name}: config.yaml version {version!r} does not track upstream {pin!r}"
            )
        changelog = (addon / "CHANGELOG.md").read_text(encoding="utf-8")
        if f"## {version}" not in changelog:
            problems.append(f"{addon.name}: CHANGELOG.md has no '## {version}' section")

    for problem in problems:
        print(f"::error::{problem}")
    print("pins are consistent" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


# ---------------------------------------------------------------------------- bump


def cmd_bump(name: str) -> int:
    tracked = TRACKED.get(name)
    if not tracked:
        raise SystemExit(f"{name} is not tracked; add it to TRACKED in {__file__}")
    addon = REPO_ROOT / name
    if not addon.is_dir():
        raise SystemExit(f"{addon} does not exist")

    notes: list[str] = []
    title = ""

    old_upstream = single_pin(addon, tracked["images"])
    new_upstream = latest_common_version(tracked["images"])
    upstream_moved = SEMVER.match(old_upstream) and version_key(new_upstream) > version_key(
        old_upstream
    )
    if upstream_moved:
        for image in tracked["images"]:
            repin(addon, image, old_upstream, new_upstream)
        images = "/".join(f"`{i.split('/')[-1]}`" for i in tracked["images"])
        note = f"Follow upstream to {images} **{new_upstream}**"
        release = tracked.get("release_url")
        if release:
            note += f" ([release notes]({release.format(version=new_upstream)}))"
        notes.append(note)
        title = f"chore({name}): follow upstream to {new_upstream}"

    base_moved = False
    if tracked.get("track_base"):
        old_base = single_pin(addon, [BASE_IMAGE])
        new_base = latest_version(BASE_IMAGE)
        base_moved = version_key(new_base) > version_key(old_base)
        if base_moved:
            repin(addon, BASE_IMAGE, old_base, new_base)
            notes.append(f"Base image `{old_base}` → **`{new_base}`**")
            if not title:
                title = f"chore({name}): update the base image to {new_base}"

    if not notes:
        print(f"{name}: nothing to update (upstream {old_upstream})")
        return _emit(updated=False, addon=name, version=addon_version(addon))

    version = new_upstream if upstream_moved else next_revision(addon_version(addon))
    set_addon_version(addon, version)

    entry = f"## {version}\n\n" + "\n".join(f"- {note}" for note in notes)
    changelog = addon / "CHANGELOG.md"
    text = changelog.read_text(encoding="utf-8")
    head, sep, rest = text.partition("\n\n")
    changelog.write_text(f"{head}{sep}{entry}\n\n{rest}", encoding="utf-8")

    print(f"{name}: {version}\n" + "\n".join(f"  - {note}" for note in notes))
    return _emit(
        updated=True,
        addon=name,
        version=version,
        title=title,
        notes="\n".join(f"- {note}" for note in notes),
    )


def _emit(**outputs) -> int:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return 0
    with open(path, "a", encoding="utf-8") as fh:
        for key, value in outputs.items():
            value = str(value).lower() if isinstance(value, bool) else str(value)
            if "\n" in value:
                fh.write(f"{key}<<PINS_EOF\n{value}\nPINS_EOF\n")
            else:
                fh.write(f"{key}={value}\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="verify the pins in the repo are consistent")
    bump = sub.add_parser("bump", help="rewrite an app's pins to the newest tags")
    bump.add_argument("--addon", required=True, choices=sorted(TRACKED))
    args = parser.parse_args()
    return cmd_check() if args.command == "check" else cmd_bump(args.addon)


if __name__ == "__main__":
    sys.exit(main())
