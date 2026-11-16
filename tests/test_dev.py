"""nix-jetbrains-project-setup-dev: argument parsing and the command line each token runs.

No test runs a command: `main()` gets a recording `run`, and `untracked_files`
is patched, so nothing here touches git, Nix or IDE files."""

import contextlib
import io
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "dev"))
import nix_jetbrains_project_setup_dev as dev  # noqa: E402

ROOT, CWD = "/repo", "/elsewhere"


def planned(*argv):
    return dev.plan(dev.parse(list(argv)), ROOT, CWD)


def parse_error(*argv):
    """The exit status and stderr of parsing `argv`, which must fail."""
    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
        try:
            dev.parse(list(argv))
        except SystemExit as error:
            return error.code, stderr.getvalue()
    raise AssertionError(f"parsing {argv} did not fail")


class TestPlan(unittest.TestCase):
    def test_test_runs_unittest_discover_from_the_root(self):
        self.assertEqual(planned("test"), ([sys.executable, "-m", "unittest", "discover", "-s", "tests"], ROOT))

    def test_test_passes_verbose_and_each_pattern(self):
        command, _ = planned("test", "-v", "-k", "Cli", "-k", "Jvm")
        self.assertEqual(command[6:], ["-v", "-k", "Cli", "-k", "Jvm"])

    def test_check_runs_nix_flake_check_with_its_arguments(self):
        self.assertEqual(planned("check"), (["nix", "flake", "check"], ROOT))
        self.assertEqual(planned("check", "-L", "--keep-going")[0], ["nix", "flake", "check", "-L", "--keep-going"])

    def test_fmt_runs_nix_fmt_from_the_root(self):
        self.assertEqual(planned("fmt"), (["nix", "fmt"], ROOT))

    def test_run_runs_the_checkout_command_in_the_callers_directory(self):
        command, cwd = planned("run", "apply", "--check", "--json", "proj")
        self.assertEqual(
            command,
            [sys.executable, os.path.join(ROOT, dev.COMMAND), "apply", "--check", "--json", "proj"],
        )
        self.assertEqual(cwd, CWD)

    def test_run_double_dash_passes_an_option_the_tool_also_has(self):
        self.assertEqual(planned("run", "--", "--help")[0][2:], ["--help"])


class TestParseErrors(unittest.TestCase):
    def test_no_command_is_a_usage_error(self):
        code, stderr = parse_error()
        self.assertEqual(code, 2)
        self.assertIn("COMMAND", stderr)

    def test_unknown_command_is_a_usage_error(self):
        self.assertEqual(parse_error("build")[0], 2)

    def test_tokens_without_passthrough_refuse_extra_arguments(self):
        for argv in (("fmt", "x"), ("test", "--keep-going")):
            with self.subTest(argv=argv):
                code, stderr = parse_error(*argv)
                self.assertEqual(code, 2)
                self.assertIn("unrecognized arguments", stderr)

    def test_help_lists_every_command_token(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), self.assertRaises(SystemExit) as caught:
            dev.parse(["--help"])
        self.assertEqual(caught.exception.code, 0)
        for token in ("test", "check", "fmt", "run"):
            self.assertIn(token, stdout.getvalue())


class TestUntrackedWarning(unittest.TestCase):
    def test_no_untracked_files_no_warning(self):
        self.assertIsNone(dev.untracked_warning([]))

    def test_lists_each_untracked_file(self):
        warning = dev.untracked_warning(["tests/test_new.py", "src/new.json"])
        self.assertIn("git add", warning)
        self.assertIn("  tests/test_new.py\n", warning)
        self.assertIn("  src/new.json\n", warning)


class TestMain(unittest.TestCase):
    def run_main(self, argv, untracked=(), result=0):
        calls, stderr = [], io.StringIO()

        def record(command, cwd):
            calls.append((command, cwd))
            return result

        with (
            mock.patch.object(dev, "untracked_files", return_value=list(untracked)),
            contextlib.redirect_stderr(stderr),
        ):
            status = dev.main(argv, root=ROOT, run=record)
        return status, calls, stderr.getvalue()

    def test_returns_the_commands_exit_status(self):
        status, calls, _ = self.run_main(["fmt"], result=3)
        self.assertEqual(status, 3)
        self.assertEqual(calls, [(["nix", "fmt"], ROOT)])

    def test_check_warns_about_untracked_files_and_still_runs(self):
        status, calls, stderr = self.run_main(["check"], untracked=["tests/test_new.py"])
        self.assertEqual(status, 0)
        self.assertIn("tests/test_new.py", stderr)
        self.assertEqual(calls, [(["nix", "flake", "check"], ROOT)])

    def test_missing_program_exits_127(self):
        def missing(command, cwd):
            raise FileNotFoundError(2, "No such file or directory", command[0])

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(dev.main(["fmt"], root=ROOT, run=missing), 127)
        self.assertIn("nix: not found", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
