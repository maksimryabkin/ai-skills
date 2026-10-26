from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "scripts" / "install.py"
spec = importlib.util.spec_from_file_location("quorum_installer", MODULE)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_both_hosts_get_complete_identical_skill_and_repeat_is_noop(self):
        receipt = installer.install(self.root, "both")
        self.assertEqual([r["status"] for r in receipt], ["installed", "installed"])
        for row in receipt:
            dest = Path(row["path"])
            self.assertEqual(installer.inventory(dest), installer.inventory(installer.SOURCE))
            self.assertTrue((dest / "references" / "hosts.md").is_file())
        self.assertEqual([r["status"] for r in installer.install(self.root, "both")], ["unchanged", "unchanged"])
        self.assertFalse((self.root / ".codex" / "config.toml").exists())
        self.assertFalse((self.root / "CLAUDE.md").exists())

    def test_preflight_preserves_foreign_skill_and_does_not_install_other_host(self):
        foreign = self.root / installer.TARGETS["claude"]
        foreign.mkdir(parents=True)
        (foreign / "SKILL.md").write_text("owner content")
        with self.assertRaises(ValueError):
            installer.install(self.root, "both")
        self.assertEqual((foreign / "SKILL.md").read_text(), "owner content")
        self.assertFalse((self.root / installer.TARGETS["codex"]).exists())

    def test_local_edits_and_added_files_block_update(self):
        dest = Path(installer.install(self.root, "codex")[0]["path"])
        original = (dest / "SKILL.md").read_text()
        (dest / "SKILL.md").write_text(original + "\nlocal edit")
        with self.assertRaises(ValueError):
            installer.install(self.root, "codex", update=True)
        (dest / "SKILL.md").write_text(original)
        (dest / "private-notes.txt").write_text("preserve")
        with self.assertRaises(ValueError):
            installer.install(self.root, "codex", update=True)
        self.assertTrue((dest / "private-notes.txt").exists())

    def test_reviewed_update_replaces_only_owned_unmodified_installation(self):
        dest = Path(installer.install(self.root, "codex")[0]["path"])
        source = self.root / "new-source"
        import shutil
        shutil.copytree(installer.SOURCE, source)
        (source / "references" / "new.md").write_text("new reference")
        with patch.object(installer, "SOURCE", source):
            with self.assertRaises(ValueError):
                installer.install(self.root, "codex")
            self.assertEqual(installer.install(self.root, "codex", update=True)[0]["status"], "updated")
            self.assertEqual(installer.inventory(dest), installer.inventory(source))

    def test_symlink_parent_cannot_redirect_installation(self):
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        (self.root / ".agents").symlink_to(elsewhere, target_is_directory=True)
        with self.assertRaises(ValueError):
            installer.install(self.root, "codex")
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_nested_record_filename_is_a_local_edit_not_ignored(self):
        dest = Path(installer.install(self.root, "codex")[0]["path"])
        (dest / "references" / installer.RECORD).write_text("private notes")
        with self.assertRaises(ValueError):
            installer.install(self.root, "codex", update=True)
        self.assertEqual((dest / "references" / installer.RECORD).read_text(), "private notes")

    def test_installation_record_from_another_repository_is_rejected(self):
        dest = Path(installer.install(self.root, "codex")[0]["path"])
        marker = dest / installer.RECORD
        record = json.loads(marker.read_text())
        record["repository"] = "https://example.com/other"
        marker.write_text(json.dumps(record))
        with self.assertRaises(ValueError):
            installer.install(self.root, "codex", update=True)


if __name__ == "__main__":
    unittest.main()
