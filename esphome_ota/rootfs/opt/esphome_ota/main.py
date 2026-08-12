"""Entry point for the ESPHome OTA Publisher add-on."""

from __future__ import annotations

import logging
import os

from aiohttp import web

from server import create_app


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name, "").strip()
    # bashio renders an unset optional as the literal string "null".
    return default if value in ("", "null") else value


def main() -> None:
    level = _env("LOG_LEVEL", "info").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="[%(levelname)s] %(name)s: %(message)s",
    )
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)

    port = int(_env("INGRESS_PORT", "8099"))
    web.run_app(create_app(), host="0.0.0.0", port=port, access_log=None, print=None)


if __name__ == "__main__":
    main()
