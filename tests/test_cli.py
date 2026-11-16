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
        err = io.StringIO()
        with self.assertRaises(SystemExit) as raised, contextlib.redirect_stderr(err):
            njps.main(["--json"])
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("--json requires --check", err.getvalue())

    def test_non_directory_fails_but_other_dirs_still_run(self):
        root = self.project()
        missing = os.path.join(self.home, "missing")
        code, _, err = self.cli(missing, root)
        self.assertEqual(code, 2)
        self.assertIn("~/missing: not a directory; skipping", err)
        self.assertEqual(self.read(self.iml), APPLIED_IML)

    def test_jvm_alone_touches_no_project(self):
        root = self.project()
        # Without --jvm the current directory would be the default project.
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(root)
        before = self.snapshot(root)
        self.assertEqual(self.cli("--jvm"), (0, "", ""))
        self.assertEqual(self.snapshot(root), before)


if __name__ == "__main__":
    unittest.main()
