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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOG = logging.getLogger("publisher")


class Publisher:
    def __init__(self, www_root: Path, publish_dir: str) -> None:
        self.www_root = www_root
        self.dir = www_root / publish_dir
        self.publish_dir = publish_dir

    def ensure_dirs(self) -> bool:
        """Create the output directory. Returns True if Home Assistant needs a restart.

        Home Assistant registers /local once at startup, guarded by an isdir
        check on the www folder, so a www folder created after boot stays
        invisible until it restarts.
        """
        needs_restart = not self.www_root.is_dir()
        self.dir.mkdir(parents=True, exist_ok=True)
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
    ) -> dict[str, Any]:
        self.ensure_dirs()
        digest = hashlib.md5(blob).hexdigest()  # noqa: S324 - ESPHome's OTA checksum is MD5
        bin_name = f"{node}.ota.bin"

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
                        "summary": summary or "Built by ESPHome OTA Server",
                    },
                }
            ],
        }
        # Manifest last: it is the pointer, and must never name a file that
        # is not on disk yet.
        self._atomic_write(
            self.dir / f"{node}.json", json.dumps(manifest, separators=(",", ":")).encode("utf-8")
        )

        record = {
            "node": node,
            "md5": digest,
            "version": version,
            "chip_family": chip_family,
            "size": len(blob),
            "published_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        LOG.info("Published %s (%s, %s bytes, %s)", node, chip_family, len(blob), digest[:8])
        return record

    def published(self, node: str) -> dict[str, Any] | None:
        manifest_path = self.dir / f"{node}.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        build = (manifest.get("builds") or [{}])[0]
        ota = build.get("ota") or {}
        return {
            "version": manifest.get("version", ""),
            "md5": ota.get("md5", ""),
            "chip_family": build.get("chipFamily", ""),
            "published_at": datetime.fromtimestamp(
                manifest_path.stat().st_mtime, tz=timezone.utc
            ).isoformat(timespec="seconds"),
        }

    def unpublish(self, node: str) -> None:
        for name in (f"{node}.json", f"{node}.ota.bin", f"{node}.ota.bin.md5"):
            (self.dir / name).unlink(missing_ok=True)

    @staticmethod
    def _atomic_write(path: Path, payload: bytes) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(payload)
        os.replace(tmp, path)
