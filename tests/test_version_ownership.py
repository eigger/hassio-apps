import sys
import unittest
import tempfile
from pathlib import Path
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop
from aiohttp import web

# Add rootfs path to sys.path
APP_DIR = Path(__file__).resolve().parent.parent / "esphome_ota" / "rootfs" / "opt" / "esphome_ota"
sys.path.insert(0, str(APP_DIR))

import metadata
import packages
import registry
import server
from publisher import Publisher


class TestVersionOwnership(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_dir.name)
        self.esphome_config = self.root / "config" / "esphome"
        self.esphome_config.mkdir(parents=True, exist_ok=True)
        self.www_root = self.root / "config" / "www"
        self.storage_dir = self.root / "data" / "published"
        self.publisher = Publisher(
            www_root=self.www_root,
            publish_dir="esphome_ota",
            storage_dir=self.storage_dir,
        )

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_ownership_detection(self):
        # 1. Device YAML has its own esphome.project:
        (self.esphome_config / "livingroom.yaml").write_text(
            """\
esphome:
  name: livingroom
  project:
    name: "me.livingroom"
    version: "2.0"
esp32:
  board: esp32dev
packages:
  ota: !include ota_server/devices/livingroom.yaml
""",
            encoding="utf-8",
        )
        packages.write_one_device_wrapper(self.esphome_config, "livingroom", "1.0.5")

        self.assertEqual(
            metadata.own_project_version(self.esphome_config, "livingroom"), "2.0"
        )

        # 2. Device YAML does not declare project:
        (self.esphome_config / "bedroom.yaml").write_text(
            """\
esphome:
  name: bedroom
esp8266:
  board: d1_mini
packages:
  ota: !include ota_server/devices/bedroom.yaml
""",
            encoding="utf-8",
        )
        packages.write_one_device_wrapper(self.esphome_config, "bedroom", "1.0.0")

        self.assertIsNone(
            metadata.own_project_version(self.esphome_config, "bedroom")
        )

        # 3. Non-existent YAML
        self.assertIsNone(
            metadata.own_project_version(self.esphome_config, "nonexistent")
        )

    def test_framework_version_not_matched_as_project_version(self):
        # Device YAML has esp32.framework.version but no esphome.project block
        (self.esphome_config / "framework_node.yaml").write_text(
            """\
esphome:
  name: framework_node
esp32:
  board: esp32dev
  framework:
    type: esp-idf
    version: 5.1.2
""",
            encoding="utf-8",
        )
        self.assertIsNone(
            metadata.own_project_version(self.esphome_config, "framework_node")
        )

    def test_transient_syntax_error_preserves_manual_wrapper(self):
        settings = server.Settings(
            www_root=self.www_root,
            esphome_config_dir=self.esphome_config,
            publish_dir="esphome_ota",
            base_url="http://ha.local:8123",
        )
        app = server.App(settings)

        # 1. Device originally created in manual mode
        (self.esphome_config / "dev.yaml").write_text(
            'esphome:\n  name: dev\n  project:\n    name: "t"\n    version: "2.0"\n',
            encoding="utf-8",
        )
        app.write_device_wrapper("dev", "2.0")
        wrapper_file = self.esphome_config / "ota_server" / "devices" / "dev.yaml"
        self.assertTrue(wrapper_file.is_file())
        self.assertIsNone(metadata.wrapper_project_version(self.esphome_config, "dev"))

        # 2. User introduces syntax error in dev.yaml while editing
        (self.esphome_config / "dev.yaml").write_text(
            "esphome:\n  name: dev\ninvalid: [yaml syntax: {unclosed\n",
            encoding="utf-8",
        )

        # 3. Re-writing wrapper during syntax error must NOT inject project: (preserve manual mode)
        app.write_device_wrapper("dev", "2.0")
        self.assertIsNone(metadata.wrapper_project_version(self.esphome_config, "dev"))

        # 4. advance_registered_version must NOT bump version during syntax error
        app.registered["dev"] = {"version": "2.0", "title": "Dev"}
        app.advance_registered_version("dev", "2.0")
        self.assertEqual(app.registered["dev"]["version"], "2.0")

    def test_wrapper_generation_modes(self):
        # Auto mode (include_project=True by default)
        written_auto = packages.write_one_device_wrapper(
            self.esphome_config, "auto_node", "1.2.3", token="token123", include_project=True
        )
        self.assertTrue(len(written_auto) > 0)
        auto_content = (self.esphome_config / "ota_server" / "devices" / "auto_node.yaml").read_text(encoding="utf-8")
        self.assertIn("esphome:\n  project:\n    name: \"local.auto_node\"\n    version: \"1.2.3\"", auto_content)
        self.assertIn("ota_device: auto_node", auto_content)
        self.assertIn("ota_slug: auto_node_token123", auto_content)
        self.assertIn("!include ../ota.yaml", auto_content)

        # Manual mode (include_project=False)
        written_manual = packages.write_one_device_wrapper(
            self.esphome_config, "manual_node", "1.2.3", token="token456", include_project=False
        )
        self.assertTrue(len(written_manual) > 0)
        manual_content = (self.esphome_config / "ota_server" / "devices" / "manual_node.yaml").read_text(encoding="utf-8")
        # Non-comment lines must not contain esphome or project blocks
        code_lines = [line for line in manual_content.splitlines() if not line.startswith("#") and line.strip()]
        self.assertNotIn("esphome:", code_lines)
        self.assertFalse(any("version:" in line for line in code_lines))
        # Mechanical parts must remain intact
        self.assertIn("ota_device: manual_node", manual_content)
        self.assertIn("ota_slug: manual_node_token456", manual_content)
        self.assertIn("!include ../ota.yaml", manual_content)

    def test_write_device_wrappers_batch_delegation(self):
        # Batch wrapper generation delegates and handles both auto and manual
        (self.esphome_config / "node_man.yaml").write_text(
            'esphome:\n  name: node_man\n  project:\n    name: "t"\n    version: "2.0"\n',
            encoding="utf-8",
        )
        (self.esphome_config / "node_auto.yaml").write_text(
            "esphome:\n  name: node_auto\n", encoding="utf-8"
        )
        devices = [
            {"node": "node_man", "version": "2.0", "own_project_version": "2.0"},
            {"node": "node_auto", "version": "1.0.0"},
        ]
        written = packages.write_device_wrappers(self.esphome_config, devices)
        self.assertTrue(len(written) >= 6)

        man_content = (self.esphome_config / "ota_server" / "devices" / "node_man.yaml").read_text(encoding="utf-8")
        auto_content = (self.esphome_config / "ota_server" / "devices" / "node_auto.yaml").read_text(encoding="utf-8")
        man_code = [line for line in man_content.splitlines() if not line.startswith("#") and line.strip()]
        self.assertNotIn("esphome:", man_code)
        self.assertIn('version: "1.0.0"', auto_content)

    def test_bump_version_cases(self):
        cases = [
            ("2026-08-19", "2026-08-19.1"),
            ("2026-08-19.1", "2026-08-19.2"),
            ("2026.08.19", "2026.08.19.1"),
            ("2026.7.4", "2026.7.4.1"),
            ("2026.7.4.1", "2026.7.4.2"),
            ("20260819", "20260819.1"),
            ("20260819.1", "20260819.2"),
            ("v260819 rev.4", "v260819 rev.5"),
            ("1.0.0", "1.0.1"),
            ("1.9", "1.10"),
            ("stable", "stable.1"),
            ("1999.12.31", "1999.12.32"),  # 20xx year limit preserves standard bump
        ]
        for src, expected in cases:
            with self.subTest(src=src, expected=expected):
                self.assertEqual(packages.bump_version(src), expected)

    def test_auto_advance_registered_version(self):
        settings = server.Settings(
            www_root=self.www_root,
            esphome_config_dir=self.esphome_config,
            publish_dir="esphome_ota",
            base_url="http://ha.local:8123",
        )
        app = server.App(settings)

        # 1. Auto mode node
        (self.esphome_config / "autonode.yaml").write_text(
            "esphome:\n  name: autonode\nesp32:\n  board: esp32dev\n",
            encoding="utf-8",
        )
        app.registered["autonode"] = {"version": "1.0.0", "title": "Auto Node"}
        app.advance_registered_version("autonode", "1.0.0")

        # Auto mode bumps version in registry and wrapper
        self.assertEqual(app.registered["autonode"]["version"], "1.0.1")
        wrapper_content = (self.esphome_config / "ota_server" / "devices" / "autonode.yaml").read_text(encoding="utf-8")
        self.assertIn('version: "1.0.1"', wrapper_content)

        # 2. Manual mode node
        (self.esphome_config / "manualnode.yaml").write_text(
            'esphome:\n  name: manualnode\n  project:\n    name: "test"\n    version: "2.0.0"\nesp32:\n  board: esp32dev\n',
            encoding="utf-8",
        )
        app.registered["manualnode"] = {"version": "1.0.0", "title": "Manual Node"}
        # Initial wrapper for manual mode should not have project block in code lines
        app.write_device_wrapper("manualnode", "1.0.0")
        manual_wrapper = (self.esphome_config / "ota_server" / "devices" / "manualnode.yaml").read_text(encoding="utf-8")
        code_lines = [line for line in manual_wrapper.splitlines() if not line.startswith("#") and line.strip()]
        self.assertNotIn("esphome:", code_lines)

        # advance_registered_version must NOT bump version in manual mode
        app.advance_registered_version("manualnode", "2.0.0")
        self.assertEqual(app.registered["manualnode"]["version"], "1.0.0")

    def test_list_devices_display_priority(self):
        settings = server.Settings(
            www_root=self.www_root,
            esphome_config_dir=self.esphome_config,
            publish_dir="esphome_ota",
            base_url="http://ha.local:8123",
        )
        app = server.App(settings)

        # Create livingroom with own project: version 2.0
        (self.esphome_config / "livingroom.yaml").write_text(
            """\
esphome:
  name: livingroom
  project:
    name: "me.livingroom"
    version: "2.0"
esp32:
  board: esp32dev
packages:
  ota: !include ota_server/devices/livingroom.yaml
""",
            encoding="utf-8",
        )
        # Registry has stale/different version "1.0.5"
        app.registered["livingroom"] = {"version": "1.0.5", "title": "Living Room"}

        # Simulate list_devices without network client
        app.load_registry()
        configs, _ = metadata.scan_esphome_dir(app.settings.esphome_config_dir)
        local = {row["node"]: row for row in configs}

        # Check resolution matching server.py:469
        node = "livingroom"
        local_row = local.get(node, {})
        rec = app.registered.get(node, {})
        own_version = (
            local_row.get("own_project_version")
            if node in local
            else metadata.own_project_version(app.settings.esphome_config_dir, node)
        )
        project_version = own_version if own_version is not None else (
            rec.get("version")
            or (
                metadata.wrapper_project_version(app.settings.esphome_config_dir, node)
                if packages.device_wrapper_exists(app.settings.esphome_config_dir, node)
                else None
            )
        )
        version_owner = "yaml" if own_version is not None else "addon"

        # Effective display version MUST be 2.0, not 1.0.5 (MISMATCH eliminated)
        self.assertEqual(own_version, "2.0")
        self.assertEqual(project_version, "2.0")
        self.assertEqual(version_owner, "yaml")

        config = metadata.read_config(self.esphome_config, "livingroom.yaml")
        eff = metadata.effective_project_version(
            self.esphome_config, "livingroom", config, self.esphome_config / "livingroom.yaml"
        )
        self.assertEqual(eff, project_version)


class TestVersionOwnershipRoutes(AioHTTPTestCase):
    async def get_application(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_dir.name)
        self.esphome_config = self.root / "config" / "esphome"
        self.esphome_config.mkdir(parents=True, exist_ok=True)
        self.www_root = self.root / "config" / "www"
        self.storage_dir = self.root / "data" / "published"

        settings = server.Settings(
            www_root=self.www_root,
            esphome_config_dir=self.esphome_config,
            publish_dir="esphome_ota",
            base_url="http://ha.local:8123",
        )
        app_instance = server.App(settings)
        aiohttp_app = web.Application()
        aiohttp_app["app"] = app_instance
        aiohttp_app.add_routes(server.routes)
        return aiohttp_app

    def tearDown(self):
        super().tearDown()
        self.tmp_dir.cleanup()

    @unittest_run_loop
    async def test_wrapper_version_manual_mode_rejection_409(self):
        app_instance: server.App = self.app["app"]

        # 1. Create a manual mode device
        (self.esphome_config / "livingroom.yaml").write_text(
            """\
esphome:
  name: livingroom
  project:
    name: "me.livingroom"
    version: "2.0"
esp32:
  board: esp32dev
""",
            encoding="utf-8",
        )
        app_instance.registered["livingroom"] = {"version": "1.0.0", "title": "Living Room"}

        # Attempt to change wrapper version -> must return 409 Conflict
        resp = await self.client.post(
            "/api/wrapper-version",
            json={"node": "livingroom", "version": "1.0.1"},
        )
        self.assertEqual(resp.status, 409)
        body = await resp.json()
        self.assertIn("error", body)
        self.assertIn("esphome.project.version", body["error"])

    @unittest_run_loop
    async def test_wrapper_version_auto_mode_success(self):
        app_instance: server.App = self.app["app"]

        # 1. Create an auto mode device (no project:)
        (self.esphome_config / "kitchen.yaml").write_text(
            """\
esphome:
  name: kitchen
esp32:
  board: esp32dev
""",
            encoding="utf-8",
        )
        app_instance.registered["kitchen"] = {"version": "1.0.0", "title": "Kitchen"}

        # Attempt to change wrapper version -> must succeed (200 OK)
        resp = await self.client.post(
            "/api/wrapper-version",
            json={"node": "kitchen", "version": "1.0.5"},
        )
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertEqual(body["version"], "1.0.5")
        self.assertEqual(app_instance.registered["kitchen"]["version"], "1.0.5")

    @unittest_run_loop
    async def test_snippet_route_ownership_and_wrapper_generation(self):
        # 1. Manual mode device snippet onboarding:
        # User already declared project: in YAML. Wrapper does not exist yet.
        (self.esphome_config / "livingroom.yaml").write_text(
            'esphome:\n  name: livingroom\n  project:\n    name: "me"\n    version: "2.0"\n',
            encoding="utf-8",
        )
        wrapper_file = self.esphome_config / "ota_server" / "devices" / "livingroom.yaml"
        self.assertFalse(wrapper_file.is_file())

        resp = await self.client.get("/api/snippet?node=livingroom")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertEqual(body["version"], "2.0")
        self.assertEqual(body["version_owner"], "yaml")
        self.assertFalse(body["has_project"])

        # Wrapper file MUST exist on disk after calling snippet route
        self.assertTrue(wrapper_file.is_file())
        # And must NOT contain project block in manual mode
        wrapper_content = wrapper_file.read_text(encoding="utf-8")
        code_lines = [line for line in wrapper_content.splitlines() if not line.startswith("#") and line.strip()]
        self.assertNotIn("esphome:", code_lines)

        # 2. Auto mode snippet:
        (self.esphome_config / "porch.yaml").write_text(
            "esphome:\n  name: porch\n", encoding="utf-8"
        )
        resp = await self.client.get("/api/snippet?node=porch")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertEqual(body["version_owner"], "addon")
        self.assertTrue(body["has_project"])
        porch_wrapper = self.esphome_config / "ota_server" / "devices" / "porch.yaml"
        self.assertTrue(porch_wrapper.is_file())
        self.assertIn("esphome:\n  project:", porch_wrapper.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
