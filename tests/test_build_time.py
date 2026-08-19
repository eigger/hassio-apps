"""Tests for metadata._parse_build_datetime — covers normal, space-padded day, and garbage inputs."""

import struct
import sys
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent / "esphome_ota" / "rootfs" / "opt" / "esphome_ota"
sys.path.insert(0, str(APP_DIR))

from metadata import (
    _find_literal_build_time,
    _find_project_version,
    _parse_build_datetime,
    parse_app_descriptor,
    ESP_APP_DESC_MAGIC,
)


class TestParseBuildDateTime(unittest.TestCase):
    def test_normal_date(self):
        self.assertEqual(_parse_build_datetime("Aug 18 2026", "17:04:29"), "2026-08-18T17:04:29")

    def test_space_padded_day(self):
        # GCC __DATE__ pads single-digit days with a space: "Aug  8 2026"
        self.assertEqual(_parse_build_datetime("Aug  8 2026", "07:04:09"), "2026-08-08T07:04:09")

    def test_all_months(self):
        months = [
            ("Jan", "01"), ("Feb", "02"), ("Mar", "03"), ("Apr", "04"),
            ("May", "05"), ("Jun", "06"), ("Jul", "07"), ("Aug", "08"),
            ("Sep", "09"), ("Oct", "10"), ("Nov", "11"), ("Dec", "12"),
        ]
        for name, num in months:
            with self.subTest(month=name):
                result = _parse_build_datetime(f"{name} 15 2026", "12:00:00")
                self.assertEqual(result, f"2026-{num}-15T12:00:00")

    def test_garbage_date_returns_none(self):
        self.assertIsNone(_parse_build_datetime("not a date", "12:00:00"))

    def test_empty_strings_return_none(self):
        self.assertIsNone(_parse_build_datetime("", ""))
        self.assertIsNone(_parse_build_datetime("Aug 18 2026", ""))
        self.assertIsNone(_parse_build_datetime("", "12:00:00"))

    def test_bad_time_returns_none(self):
        self.assertIsNone(_parse_build_datetime("Aug 18 2026", "bad"))

    def test_unknown_month_returns_none(self):
        self.assertIsNone(_parse_build_datetime("Xyz 18 2026", "12:00:00"))


class TestParseAppDescriptor(unittest.TestCase):
    """Integration: build a synthetic esp_app_desc_t blob and verify round-trip."""

    def _make_blob(
        self, version: str, project: str, time_str: str, date_str: str, idf: str, tail: bytes = b""
    ) -> bytes:
        # esp_image_header_t (24 bytes) + app descriptor starting at offset 0x20 (32)
        # Total we need: 0x20 (header) + 0x90 (end of idf_ver field) + 32 = 0xB0 bytes minimum
        blob = bytearray(0xC0)
        blob[0] = 0xE9  # ESP_IMAGE_MAGIC
        # ESP32 header sanity guard fields
        blob[19] = blob[20] = blob[21] = blob[22] = 0
        blob[23] = 0  # hash_appended

        # Write magic at 0x20
        struct.pack_into("<I", blob, 0x20, ESP_APP_DESC_MAGIC)

        def write_str(offset, s, size):
            b = s.encode("utf-8")[:size]
            blob[offset:offset + len(b)] = b

        write_str(0x30, version, 32)    # version
        write_str(0x50, project, 32)    # project_name
        write_str(0x70, time_str, 16)   # time
        write_str(0x80, date_str, 16)   # date
        write_str(0x90, idf, 32)        # idf_ver

        return bytes(blob) + tail

    def test_normal_descriptor(self):
        blob = self._make_blob("2026.7.3", "me.proj", "17:04:29", "Aug 18 2026", "v5.1.2")
        result = parse_app_descriptor(blob)
        self.assertEqual(result["version"], "2026.7.3")
        self.assertEqual(result["project_name"], "me.proj")
        self.assertEqual(result["idf_version"], "v5.1.2")
        self.assertEqual(result["build_time"], "2026-08-18T17:04:29")

    def test_space_padded_day(self):
        blob = self._make_blob("1.0.0", "proj", "07:04:09", "Aug  8 2026", "v5.1.2")
        result = parse_app_descriptor(blob)
        self.assertEqual(result["build_time"], "2026-08-08T07:04:09")

    def test_bad_date_no_build_time_key(self):
        blob = self._make_blob("1.0.0", "proj", "12:00:00", "not a date", "v5.1.2")
        result = parse_app_descriptor(blob)
        self.assertNotIn("build_time", result)
        self.assertNotIn("build_time_raw", result)  # dead code was removed

    def test_wrong_magic_returns_empty(self):
        blob = bytearray(0xC0)
        blob[0] = 0xE9
        result = parse_app_descriptor(bytes(blob))
        self.assertEqual(result, {})

    def test_reproducible_build_falls_back_to_literal_time_and_finds_project_version(self):
        # ESPHome's real-world shape: CONFIG_APP_REPRODUCIBLE_BUILD zeroes the
        # struct's time/date fields, but the boot-log banner and ESPHome's own
        # compiled-in "%Y-%m-%d %H:%M:%S %z" timestamp are still present as
        # separate .rodata literals elsewhere in the image.
        tail = (
            b"ESPHome version 2026.7.4 compiled on %s\x00"
            b"Project local.esp-colorado-tab5 version v260819 rev.1\x00"
            b"\x00setup() finished successfully!\x00"
            b"2026-08-19 08:54:27 +0900\x00"
        )
        blob = self._make_blob("2026.7.4", "esp-colorado-tab5", "", "", "v5.5.5", tail=tail)
        result = parse_app_descriptor(blob)
        self.assertEqual(result["version"], "2026.7.4")
        self.assertEqual(result["project_name"], "esp-colorado-tab5")
        self.assertEqual(result["build_time"], "2026-08-19 08:54:27 +0900")
        self.assertEqual(result["project_literal_name"], "local.esp-colorado-tab5")
        self.assertEqual(result["project_version"], "v260819 rev.1")

    def test_struct_time_wins_over_literal_when_both_present(self):
        tail = b"2099-01-01 00:00:00 +0000\x00"
        blob = self._make_blob("1.0.0", "proj", "17:04:29", "Aug 18 2026", "v5.1.2", tail=tail)
        result = parse_app_descriptor(blob)
        self.assertEqual(result["build_time"], "2026-08-18T17:04:29")

    def test_no_logger_no_project_version_key(self):
        # logger.level: NONE strips ESP_LOGI calls at compile time, so the
        # boot-log banner never makes it into .rodata — no project_version.
        blob = self._make_blob("2026.7.4", "esp-colorado-tab5", "", "", "v5.5.5")
        result = parse_app_descriptor(blob)
        self.assertNotIn("project_version", result)
        self.assertNotIn("project_literal_name", result)


class TestFindProjectVersion(unittest.TestCase):
    def test_finds_banner(self):
        blob = b"garbage\x00Project my.node version v1.2.3-rc1\x00more"
        self.assertEqual(_find_project_version(blob), ("my.node", "v1.2.3-rc1"))

    def test_no_banner_returns_none(self):
        self.assertIsNone(_find_project_version(b"nothing interesting here"))

    def test_unterminated_string_not_matched(self):
        # No trailing NUL before EOF — not a complete .rodata literal.
        self.assertIsNone(_find_project_version(b"Project my.node version v1.2.3"))


class TestFindLiteralBuildTime(unittest.TestCase):
    def test_with_timezone_offset(self):
        blob = b"\x00garbage\x002026-08-19 08:54:27 +0900\x00tail"
        self.assertEqual(_find_literal_build_time(blob), "2026-08-19 08:54:27 +0900")

    def test_without_timezone_offset(self):
        blob = b"\x002026-08-19 08:54:27\x00tail"
        self.assertEqual(_find_literal_build_time(blob), "2026-08-19 08:54:27")

    def test_no_match_returns_none(self):
        self.assertIsNone(_find_literal_build_time(b"no timestamp in here at all"))


if __name__ == "__main__":
    unittest.main()
