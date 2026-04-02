from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from repo_harness_lab.shared.files import build_patch, collect_changed_files


class SharedFilesTests(unittest.TestCase):
    def test_collect_changed_files_and_build_patch_ignore_noise(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            target.mkdir()

            (source / "same.txt").write_text("same\n", encoding="utf8")
            (target / "same.txt").write_text("same\n", encoding="utf8")

            (source / "modify.txt").write_text("before\n", encoding="utf8")
            (target / "modify.txt").write_text("after\n", encoding="utf8")

            (source / "delete.txt").write_text("gone\n", encoding="utf8")
            (target / "add.txt").write_text("new\n", encoding="utf8")

            ignored_dir = target / "__pycache__"
            ignored_dir.mkdir()
            (ignored_dir / "noise.pyc").write_bytes(b"noise")

            changed = collect_changed_files(source, target)
            patch = build_patch(source, target)

            self.assertEqual(changed, ("add.txt", "delete.txt", "modify.txt"))
            self.assertIn("diff --git a/add.txt b/add.txt", patch)
            self.assertIn("+++ b/add.txt", patch)
            self.assertIn("--- a/delete.txt", patch)
            self.assertIn("-before", patch)
            self.assertIn("+after", patch)
            self.assertNotIn("noise.pyc", patch)


if __name__ == "__main__":
    unittest.main()
