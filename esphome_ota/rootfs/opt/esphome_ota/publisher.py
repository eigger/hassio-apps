"""Publish firmware into Home Assistant's /local static path.

Layout under ``<config>/www/<publish_dir>/``:

    livingroom.ota.bin        the firmware, overwritten in place
    livingroom.ota.bin.md5    hex digest, for ota.http_request.flash's md5_url
    livingroom.json           ESP-Web-Tools manifest, for update.http_request

The manifest's ``ota.path`` carries a ``?v=<md5 prefix>`` cache buster. Home
Assistant stamps 31-day cache headers on everything under /local, so a proxy
in front of it (a Cloudflare tunnel, say) would otherwise keep serving a stale
``.bin`` — that extension is cached by default, the ``.json`` is not.

Binaries are written to a temp file and renamed into place. On Linux a rename
swaps the directory entry while any in-flight download keeps reading the old
inode, so republishing mid-download cannot corrupt a device's update.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOG = logging.getLogger("publisher")


TOKEN_SUFFIX_RE = re.compile(r"^(.+)_([0-9a-fA-F]{32})$")


class Publisher:
    def __init__(self, www_root: Path, publish_dir: str, storage_dir: Path | None = None) -> None:
        self.www_root = www_root
        self.dir = www_root / publish_dir
        self.publish_dir = publish_dir
        self.storage_dir = storage_dir or Path("/data/firmware")

    def ensure_dirs(self) -> bool:
        """Create the output and storage directories. Returns True if Home Assistant needs a restart."""
        needs_restart = not self.www_root.is_dir()
        self.dir.mkdir(parents=True, exist_ok=True)
        try:
            self.storage_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            # Fallback if /data is not writable (e.g. running in local test environment)
            self.storage_dir = self.www_root.parent / "esphome" / "ota_server" / ".firmware"
            self.storage_dir.mkdir(parents=True, exist_ok=True)
        if needs_restart:
            LOG.warning(
                "Created %s — Home Assistant must be restarted once before /local works",
                self.www_root,
            )
        return needs_restart

    def publish(
        self,
        node: str,
        blob: bytes,
        chip_family: str,
        version: str,
        title: str,
        summary: str = "",
        token: str = "",
    ) -> dict[str, Any]:
        self.ensure_dirs()
        digest = hashlib.md5(blob).hexdigest()  # noqa: S324 - ESPHome's OTA checksum is MD5
        slug = f"{node}_{token}" if token else node
        bin_name = f"{slug}.ota.bin"

        # 1. Save in private add-on storage (for quick 1-click re-activation)
        self._atomic_write(self.storage_dir / bin_name, blob)
        self._atomic_write((self.storage_dir / f"{bin_name}.md5"), digest.encode("ascii"))

        # 2. Publish to Home Assistant /local
        self._atomic_write(self.dir / bin_name, blob)
        self._atomic_write((self.dir / f"{bin_name}.md5"), digest.encode("ascii"))

        manifest = {
            "name": title or node,
            "version": version,
            "builds": [
                {
                    "chipFamily": chip_family,
                    # Relative on purpose: ESPHome resolves it against the
                    # manifest's own URL, so the same files work over the LAN
                    # and through a remote tunnel with no rewriting.
                    "ota": {
                        "md5": digest,
                        "path": f"{bin_name}?v={digest[:8]}",
                        "summary": summary or "Built by ESPHome OTA Publisher",
                    },
                }
            ],
        }
        manifest_bytes = json.dumps(manifest, separators=(",", ":")).encode("utf-8")
        # Manifest in both places:
        self._atomic_write(self.dir / f"{slug}.json", manifest_bytes)
        self._atomic_write(self.storage_dir / f"{slug}.json", manifest_bytes)

        record = {
            "node": node,
            "token": token,
            "slug": slug,
            "md5": digest,
            "version": version,
            "chip_family": chip_family,
            "size": len(blob),
            "published_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "has_bin": True,
            "has_stashed_bin": True,
        }
        LOG.info("Published %s (slug=%s, %s, %s bytes, %s)", node, slug, chip_family, len(blob), digest[:8])
        return record

    def deactivate_binary(self, node: str, token: str = "") -> bool:
        """Deactivate (hide) the binary from /local, keeping it in add-on storage and keeping .json manifest in /local."""
        self.ensure_dirs()
        slug = f"{node}_{token}" if token else node

        # Ensure binaries and manifest are in storage before unlinking from /local
        for s in {slug, node}:
            bin_src = self.dir / f"{s}.ota.bin"
            bin_dst = self.storage_dir / f"{s}.ota.bin"
            if bin_src.is_file() and not bin_dst.is_file():
                self._atomic_write(bin_dst, bin_src.read_bytes())
                md5_src = self.dir / f"{s}.ota.bin.md5"
                if md5_src.is_file():
                    self._atomic_write(self.storage_dir / f"{s}.ota.bin.md5", md5_src.read_bytes())
                json_src = self.dir / f"{s}.json"
                if json_src.is_file():
                    self._atomic_write(self.storage_dir / f"{s}.json", json_src.read_bytes())

        # Delete all binary variations from /local public path (both slug and legacy node)
        for s in {slug, node}:
            for name in (f"{s}.ota.bin", f"{s}.ota.bin.md5"):
                (self.dir / name).unlink(missing_ok=True)
        LOG.info("Deactivated firmware binary for %s (slug=%s, removed from /local, preserved in storage)", node, slug)
        return True

    def activate_binary(self, node: str, token: str = "") -> bool:
        """Activate (deploy) the stashed binary from add-on storage back to /local."""
        self.ensure_dirs()
        slug = f"{node}_{token}" if token else node
        bin_stashed = self.storage_dir / f"{slug}.ota.bin"
        if not bin_stashed.is_file():
            # Fallback to node without token for legacy stashes
            bin_stashed = self.storage_dir / f"{node}.ota.bin"
        if not bin_stashed.is_file():
            raise FileNotFoundError(f"No stashed firmware binary found for {node} (slug={slug}).")

        # Deploy binary and md5 to /local
        self._atomic_write(self.dir / f"{slug}.ota.bin", bin_stashed.read_bytes())
        md5_stashed = self.storage_dir / f"{slug}.ota.bin.md5"
        if not md5_stashed.is_file():
            md5_stashed = self.storage_dir / f"{node}.ota.bin.md5"
        if md5_stashed.is_file():
            self._atomic_write(self.dir / f"{slug}.ota.bin.md5", md5_stashed.read_bytes())

        # Ensure manifest is present in /local
        json_stashed = self.storage_dir / f"{slug}.json"
        if not json_stashed.is_file():
            json_stashed = self.storage_dir / f"{node}.json"
        if json_stashed.is_file() and not (self.dir / f"{slug}.json").is_file():
            self._atomic_write(self.dir / f"{slug}.json", json_stashed.read_bytes())

        LOG.info("Activated firmware binary for %s (slug=%s, deployed to /local)", node, slug)
        return True

    def delete_binary(self, node: str, token: str = "") -> None:
        """Delete only the .ota.bin and .ota.bin.md5 from /local (alias for deactivate)."""
        self.deactivate_binary(node, token=token)

    def published(self, node: str, token: str = "") -> dict[str, Any] | None:
        slug = f"{node}_{token}" if token else node
        manifest_path = self.dir / f"{slug}.json"
        effective_token = token
        effective_slug = slug

        if not manifest_path.is_file():
            manifest_path = self.storage_dir / f"{slug}.json"

        # If not found with token, try fallback to un-tokenized legacy node filename
        if not manifest_path.is_file() and token:
            manifest_path = self.dir / f"{node}.json"
            if manifest_path.is_file():
                effective_token = ""
                effective_slug = node
            else:
                manifest_path = self.storage_dir / f"{node}.json"
                if manifest_path.is_file():
                    effective_token = ""
                    effective_slug = node

        if not manifest_path.is_file():
            return None

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        build = (manifest.get("builds") or [{}])[0]
        ota = build.get("ota") or {}

        bin_local = self.dir / f"{effective_slug}.ota.bin"
        if not bin_local.is_file() and effective_slug != node:
            bin_local = self.dir / f"{node}.ota.bin"

        bin_stashed = self.storage_dir / f"{effective_slug}.ota.bin"
        if not bin_stashed.is_file() and effective_slug != node:
            bin_stashed = self.storage_dir / f"{node}.ota.bin"

        has_bin = bin_local.is_file()
        has_stashed_bin = bin_stashed.is_file()
        bin_size = (
            bin_local.stat().st_size
            if has_bin
            else (bin_stashed.stat().st_size if has_stashed_bin else 0)
        )
        return {
            "node": node,
            "token": effective_token,
            "slug": effective_slug,
            "title": manifest.get("name", node),
            "version": manifest.get("version", ""),
            "summary": ota.get("summary", ""),
            "md5": ota.get("md5", ""),
            "chip_family": build.get("chipFamily", ""),
            "has_bin": has_bin,
            "has_stashed_bin": has_stashed_bin,
            "bin_size": bin_size,
            "published_at": datetime.fromtimestamp(
                manifest_path.stat().st_mtime, tz=timezone.utc
            ).isoformat(timespec="seconds"),
        }

    def list_published(self, registered: dict[str, dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
        """Every published node's manifest, read from disk (both /local and storage).

        Always keys by node name (never by slug) to prevent duplicate ghost rows.
        """
        result: dict[str, dict[str, Any]] = {}
        seen_stems: set[str] = set()

        # 1. First pass: inspect registered devices
        if registered:
            for node, rec in registered.items():
                tok = rec.get("token") or ""
                record = self.published(node, token=tok)
                if record:
                    result[node] = record
                seen_stems.add(node)
                if tok:
                    seen_stems.add(f"{node}_{tok}")

        # 2. Second pass: scan disk for un-registered published files
        for d in (self.dir, self.storage_dir):
            if d.is_dir():
                for manifest_path in d.glob("*.json"):
                    stem = manifest_path.stem
                    if stem in seen_stems:
                        continue
                    seen_stems.add(stem)

                    # Check if stem is formatted as {node}_{32hex}
                    m = TOKEN_SUFFIX_RE.match(stem)
                    if m:
                        node_name = m.group(1)
                        tok = m.group(2)
                        seen_stems.add(node_name)
                        if node_name not in result:
                            record = self.published(node_name, token=tok)
                            if record:
                                result[node_name] = record
                    else:
                        if stem not in result:
                            record = self.published(stem, token="")
                            if record:
                                result[stem] = record
        return result

    def unpublish(self, node: str, token: str = "") -> None:
        """Delete all published files from /local and add-on storage for slug and legacy."""
        slug = f"{node}_{token}" if token else node
        for s in {slug, node}:
            for name in (f"{s}.json", f"{s}.ota.bin", f"{s}.ota.bin.md5"):
                (self.dir / name).unlink(missing_ok=True)
                (self.storage_dir / name).unlink(missing_ok=True)

    @staticmethod
    def _atomic_write(path: Path, payload: bytes) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(payload)
        os.replace(tmp, path)
