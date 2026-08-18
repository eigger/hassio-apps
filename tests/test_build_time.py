"""Tests for metadata._parse_build_datetime — covers normal, space-padded day, and garbage inputs."""

import struct
import sys
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent / "esphome_ota" / "rootfs" / "opt" / "esphome_ota"
sys.path.insert(0, str(APP_DIR))

from metadata import _parse_build_datetime, parse_app_descriptor, ESP_APP_DESC_MAGIC


class TestParseBuildDateTime(unittest.TestCase):
    def test_normal_date(self):
        assert _parse_build_datetime("Aug 18 2026", "17:04:29") == "2026-08-18T17:04:29"

    def test_space_padded_day(self):
        # GCC __DATE__ pads single-digit days with a space: "Aug  8 2026"
        assert _parse_build_datetime("Aug  8 2026", "07:04:09") == "2026-08-08T07:04:09"

    def test_all_months(self):
        months = [
            ("Jan", "01"), ("Feb", "02"), ("Mar", "03"), ("Apr", "04"),
            ("May", "05"), ("Jun", "06"), ("Jul", "07"), ("Aug", "08"),
            ("Sep", "09"), ("Oct", "10"), ("Nov", "11"), ("Dec", "12"),
        ]
        for name, num in months:
            result = _parse_build_datetime(f"{name} 15 2026", "12:00:00")
            assert result == f"2026-{num}-15T12:00:00", f"Failed for month {name}"

    def test_garbage_date_returns_none(self):
        assert _parse_build_datetime("not a date", "12:00:00") is None

    def test_empty_strings_return_none(self):
        assert _parse_build_datetime("", "") is None
        assert _parse_build_datetime("Aug 18 2026", "") is None
        assert _parse_build_datetime("", "12:00:00") is None

    def test_bad_time_returns_none(self):
        assert _parse_build_datetime("Aug 18 2026", "bad") is None

    def test_unknown_month_returns_none(self):
        assert _parse_build_datetime("Xyz 18 2026", "12:00:00") is None


class TestParseAppDescriptor(unittest.TestCase):
    """Integration: build a synthetic esp_app_desc_t blob and verify round-trip."""

    def _make_blob(self, version: str, project: str, time_str: str, date_str: str, idf: str) -> bytes:
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

        return bytes(blob)

    def test_normal_descriptor(self):
        blob = self._make_blob("2026.7.3", "me.proj", "17:04:29", "Aug 18 2026", "v5.1.2")
        result = parse_app_descriptor(blob)
        assert result["version"] == "2026.7.3"
        assert result["project_name"] == "me.proj"
        assert result["idf_version"] == "v5.1.2"
        assert result["build_time"] == "2026-08-18T17:04:29"

    def test_space_padded_day(self):
        blob = self._make_blob("1.0.0", "proj", "07:04:09", "Aug  8 2026", "v5.1.2")
        result = parse_app_descriptor(blob)
        assert result["build_time"] == "2026-08-08T07:04:09"

    def test_bad_date_no_build_time_key(self):
        blob = self._make_blob("1.0.0", "proj", "12:00:00", "not a date", "v5.1.2")
        result = parse_app_descriptor(blob)
        assert "build_time" not in result
        assert "build_time_raw" not in result  # dead code was removed

    def test_wrong_magic_returns_empty(self):
        blob = bytearray(0xC0)
        blob[0] = 0xE9
        result = parse_app_descriptor(bytes(blob))
        assert result == {}


if __name__ == "__main__":
    unittest.main()
