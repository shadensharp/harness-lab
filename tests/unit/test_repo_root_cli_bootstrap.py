from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


class RepoRootCliBootstrapTests(unittest.TestCase):
    def test_cli_module_runs_from_repo_root_without_pythonpath(self) -> None:
        runtime_root = Path(tempfile.mkdtemp()) / "runtime"
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env["REPO_HARNESS_LAB_RUNTIME_ROOT"] = str(runtime_root)

        result = subprocess.run(
            [sys.executable, "-m", "repo_harness_lab.cli.main", "show-settings"],
            cwd=REPO_ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["paths"]["runtime_root"], str(runtime_root))


if __name__ == "__main__":
    unittest.main()
