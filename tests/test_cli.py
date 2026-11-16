"""End-to-end tests for the command line: argument handling and --all."""

import contextlib
import io
import os
import unittest

from support import APPLIED_IML, Base, njps


class CliTests(Base):
    def test_all_runs_config_projects_and_jvm(self):
        root = self.project()
        os.makedirs(os.path.join(self.jetbrains, "PyCharm2026.2"))
        self.config({"projects": {"~/proj": {}}, "jvmOptions": {"-XX:+UseG1GC": True}})
        self.assertEqual(self.cli("--all")[0], 0)
        self.assertEqual(self.read(self.iml), APPLIED_IML)
        self.assertIn("-XX:+UseG1GC", self.read(os.path.join(self.jetbrains, "PyCharm2026.2", "pycharm.vmoptions")))

    def test_json_needs_check(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            njps.main(["--json"])

    def test_nix_attr(self):
        self.assertEqual(njps.nix_attr("result"), "result")
        self.assertEqual(njps.nix_attr("result-*"), '"result-*"')
        self.assertEqual(njps.nix_attr(".nix"), '".nix"')



if __name__ == "__main__":
    unittest.main()
