import sys
import unittest
import tempfile
import json
from pathlib import Path

# Add rootfs path to sys.path
APP_DIR = Path(__file__).resolve().parent.parent / "esphome_ota" / "rootfs" / "opt" / "esphome_ota"
sys.path.insert(0, str(APP_DIR))

import registry
import packages
import server
from publisher import Publisher


class TestSecretTokenOTA(unittest.TestCase):
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

    def test_registry_token_generation(self):
        # 1. New device registration automatically gets a 32-character token
        data = {}
        rec = registry.upsert(data, "livingroom", "1.0.0", "Living Room")
        self.assertIn("token", rec)
        self.assertEqual(len(rec["token"]), 32)
        self.assertEqual(registry.get_token(data, "livingroom"), rec["token"])
        self.assertEqual(registry.get_slug(data, "livingroom"), f"livingroom_{rec['token']}")

        # 2. Saving and loading persists token
        registry.save(self.esphome_config, data)
        loaded = registry.load(self.esphome_config)
        self.assertEqual(loaded["livingroom"]["token"], rec["token"])

        # 3. Existing device update preserves existing token
        updated = registry.upsert(loaded, "livingroom", "1.0.1", "Living Room")
        self.assertEqual(updated["token"], rec["token"])

    def test_packages_slug_substitution(self):
        # Write packages
        packages.write_packages(self.esphome_config, "https://my-ha.duckdns.org", "esphome_ota")
        update_yaml = (self.esphome_config / "ota_server" / "update.yaml").read_text()
        self.assertIn("${ota_slug}.json", update_yaml)

        # Write wrapper with token
        token = "a8f3b9c2e17d904f8e5b6c7a1d2e3f4a"
        packages.write_one_device_wrapper(self.esphome_config, "livingroom", "1.0.1", token=token)
        
        wrapper_path = self.esphome_config / "ota_server" / "devices" / "livingroom.yaml"
        self.assertTrue(wrapper_path.is_file())
        content = wrapper_path.read_text()
        self.assertIn("ota_device: livingroom", content)
        self.assertIn(f"ota_slug: livingroom_{token}", content)

    def test_publisher_token_slug_publish_and_deactivate(self):
        token = "a8f3b9c2e17d904f8e5b6c7a1d2e3f4a"
        blob = b"\xe9\x00\x00\x00_test_firmware_binary_content_12345"
        
        # 1. Publish with token
        record = self.publisher.publish(
            node="livingroom",
            blob=blob,
            chip_family="ESP32",
            version="1.0.1",
            title="Living Room",
            summary="New features",
            token=token,
        )
        self.assertEqual(record["token"], token)
        self.assertEqual(record["slug"], f"livingroom_{token}")

        # Check files created in /local
        pub_dir = self.www_root / "esphome_ota"
        self.assertTrue((pub_dir / f"livingroom_{token}.ota.bin").is_file())
        self.assertTrue((pub_dir / f"livingroom_{token}.json").is_file())

        # 2. Deactivate binary (both slug and legacy binaries removed from /local)
        (pub_dir / "livingroom.ota.bin").write_bytes(blob)
        (pub_dir / "livingroom.ota.bin.md5").write_bytes(b"dummy")

        self.publisher.deactivate_binary("livingroom", token=token)
        self.assertFalse((pub_dir / f"livingroom_{token}.ota.bin").is_file())
        self.assertFalse((pub_dir / "livingroom.ota.bin").is_file())
        self.assertFalse((pub_dir / "livingroom.ota.bin.md5").is_file())

        # Check published status reports has_bin = False
        pub_status = self.publisher.published("livingroom", token=token)
        self.assertFalse(pub_status["has_bin"])
        self.assertTrue(pub_status["has_stashed_bin"])

    def test_list_published_no_ghost_duplicate_devices(self):
        token = "a8f3b9c2e17d904f8e5b6c7a1d2e3f4a"
        blob = b"\xe9\x00\x00\x00_test_firmware_binary"
        self.publisher.publish(
            node="bedroom",
            blob=blob,
            chip_family="ESP32",
            version="1.0.0",
            title="Bedroom",
            summary="",
            token=token,
        )
        registered = {"bedroom": {"token": token}}
        published = self.publisher.list_published(registered)

        # Keys must only contain 'bedroom', NOT 'bedroom_a8f3b9c2e17d904f8e5b6c7a1d2e3f4a'
        self.assertEqual(list(published.keys()), ["bedroom"])
        self.assertEqual(published["bedroom"]["node"], "bedroom")
        self.assertEqual(published["bedroom"]["token"], token)

    def test_load_registry_backfill_preserves_legacy_and_tokens(self):
        # 1. Legacy device published on disk without token
        blob = b"\xe9\x00\x00\x00_test_firmware_legacy"
        self.publisher.publish(
            node="legacy_porch",
            blob=blob,
            chip_family="ESP8266",
            version="1.0.0",
            title="Legacy Porch",
            summary="",
            token="",
        )

        # 2. Tokenized device published on disk with token
        token_attic = "11223344556677889900aabbccddeeff"
        self.publisher.publish(
            node="attic",
            blob=blob,
            chip_family="ESP32",
            version="1.0.0",
            title="Attic",
            summary="",
            token=token_attic,
        )

        # 3. Simulate App load_registry with injected Settings
        settings = server.Settings(
            www_root=self.www_root,
            esphome_config_dir=self.esphome_config,
            publish_dir="esphome_ota",
        )
        app = server.App(settings)
        app.load_registry()

        # Legacy device must have token == "" to preserve OTA polling path
        self.assertIn("legacy_porch", app.registered)
        self.assertEqual(app.registered["legacy_porch"]["token"], "")

        # Tokenized device must preserve its token
        self.assertIn("attic", app.registered)
        self.assertEqual(app.registered["attic"]["token"], token_attic)

        # Must not contain ghost duplicate keys
        self.assertNotIn(f"attic_{token_attic}", app.registered)

    def test_server_app_creation(self):
        app = server.create_app()
        self.assertIsNotNone(app)
        self.assertIn("app", app)


if __name__ == "__main__":
    unittest.main()
