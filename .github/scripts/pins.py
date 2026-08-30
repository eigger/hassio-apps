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
    pins.py bump --addon NAME  pull the newest upstream tag and rewrite the pins

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

# Apps whose version tracks an upstream release. `images` must all publish the same
# tag — they are built and released together upstream.
TRACKED = {
    "garage": {
        "images": ["eigger/garage-api", "eigger/garage-web"],
        "release_url": "https://github.com/eigger/garage/releases/tag/v{version}",
    },
}

# The add-on base image is pinned per app but is not what drives an app's version,
# so `check` only verifies it is consistent inside each app.
BASE_IMAGE = "hassio-addons/base"

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
TEXT_SUFFIXES = {".yaml", ".yml", ".md", ".sh", ".conf", ".json", ""}


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


def latest_common_version(images: list[str]) -> str:
    shared: set[str] | None = None
    for image in images:
        semver = {t for t in ghcr_tags(image) if SEMVER.match(t)}
        shared = semver if shared is None else (shared & semver)
    if not shared:
        raise SystemExit(f"no semver tag published by all of {', '.join(images)}")
    return max(shared, key=lambda v: tuple(int(p) for p in v.split(".")))


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


def addon_version(addon: Path) -> str:
    text = (addon / "config.yaml").read_text(encoding="utf-8")
    match = re.search(r'^version:\s*"?([^"\n]+)"?\s*$', text, re.MULTILINE)
    if not match:
        raise SystemExit(f"{addon.name}/config.yaml has no version")
    return match.group(1).strip()


# --------------------------------------------------------------------------- check


def cmd_check() -> int:
    problems: list[str] = []
    for addon in addon_dirs():
        for image in TRACKED.get(addon.name, {}).get("images", []) + [BASE_IMAGE]:
            tags = {t for tagset in pinned_tags(addon, image).values() for t in tagset}
            if len(tags) > 1:
                where = ", ".join(
                    f"{p.relative_to(REPO_ROOT)}={'/'.join(sorted(t))}"
                    for p, t in pinned_tags(addon, image).items()
                )
                problems.append(f"{addon.name}: {image} pinned to {sorted(tags)} ({where})")

        tracked = TRACKED.get(addon.name)
        if not tracked:
            continue
        upstream = {
            t
            for image in tracked["images"]
            for tagset in pinned_tags(addon, image).values()
            for t in tagset
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

    current = {
        t
        for image in tracked["images"]
        for tagset in pinned_tags(addon, image).values()
        for t in tagset
    }
    if len(current) != 1:
        raise SystemExit(f"{name}: images disagree on the current tag {sorted(current)}")
    old = current.pop()
    new = latest_common_version(tracked["images"])

    key = lambda v: tuple(int(p) for p in v.split("."))
    if not SEMVER.match(old) or key(new) <= key(old):
        print(f"{name}: already on the newest upstream release ({old})")
        return _emit(updated=False, addon=name, previous=old, version=old)

    for image in tracked["images"]:
        for path in pinned_tags(addon, image):
            text = path.read_text(encoding="utf-8")
            path.write_text(
                text.replace(f"ghcr.io/{image}:{old}", f"ghcr.io/{image}:{new}"),
                encoding="utf-8",
            )

    config = addon / "config.yaml"
    config.write_text(
        re.sub(
            r'^version:\s*"?[^"\n]+"?\s*$',
            f'version: "{new}"',
            config.read_text(encoding="utf-8"),
            count=1,
            flags=re.MULTILINE,
        ),
        encoding="utf-8",
    )

    images = "/".join(f"`{i.split('/')[-1]}`" for i in tracked["images"])
    entry = f"## {new}\n\n- Follow upstream to {images} **{new}**"
    release = tracked.get("release_url")
    if release:
        entry += f" ([release notes]({release.format(version=new)}))"
    changelog = addon / "CHANGELOG.md"
    text = changelog.read_text(encoding="utf-8")
    head, sep, rest = text.partition("\n\n")
    changelog.write_text(f"{head}{sep}{entry}\n\n{rest}", encoding="utf-8")

    print(f"{name}: {old} -> {new}")
    return _emit(updated=True, addon=name, previous=old, version=new)


def _emit(**outputs) -> int:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            for key, value in outputs.items():
                fh.write(f"{key}={str(value).lower() if isinstance(value, bool) else value}\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="verify the pins in the repo are consistent")
    bump = sub.add_parser("bump", help="rewrite an app's pins to the newest upstream tag")
    bump.add_argument("--addon", required=True, choices=sorted(TRACKED))
    args = parser.parse_args()
    return cmd_check() if args.command == "check" else cmd_bump(args.addon)


if __name__ == "__main__":
    sys.exit(main())
