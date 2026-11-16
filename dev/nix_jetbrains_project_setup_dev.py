#!/usr/bin/env python3
"""nix-jetbrains-project-setup-dev: the commands run while working on this repository.

Each command token maps to one command line (`plan()`, pure) that `main()`
runs and whose exit status it returns. `test`, `check` and `fmt` run from
the repository root; `run` runs the command from the checkout in the
caller's directory, since it works on the current directory."""

import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMMAND = os.path.join("src", "nix_jetbrains_project_setup.py")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="nix-jetbrains-project-setup-dev",
        description="Run this repository's checks, formatter and command from the checkout.",
    )
    commands = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)

    test = commands.add_parser(
        "test",
        help="run the unittest suite (python3 -m unittest discover -s tests)",
        description="Run the unittest suite. Fast; no Nix build.",
    )
    test.add_argument("-v", "--verbose", action="store_true", help="list each test as it runs")
    test.add_argument(
        "-k",
        dest="patterns",
        metavar="PATTERN",
        action="append",
        default=[],
        help="run only tests whose name matches PATTERN (repeatable)",
    )

    commands.add_parser(
        "check",
        usage="%(prog)s [-h] [NIX_ARG ...]",
        help="run nix flake check: formatting, the package build and its tests, the Home Manager module",
        description="Run `nix flake check`; it must pass before committing. "
        "Nix sees only tracked files, so it warns about untracked ones first. "
        "Any other arguments go to nix flake check.",
    )

    commands.add_parser(
        "fmt",
        help="format every file with nix fmt (nixfmt, ruff)",
        description="Format the repository with `nix fmt` (treefmt: nixfmt and ruff).",
    )

    commands.add_parser(
        "run",
        usage="%(prog)s [-h] [ARG ...]",
        help="run nix-jetbrains-project-setup from the checkout, in the current directory",
        description="Run src/nix_jetbrains_project_setup.py with the given arguments, "
        "without installing it; put -- before an argument that is also an option here, such as -- --help. "
        "It acts on real IDE and project files, as the installed command does.",
    )
    return parser


PASSTHROUGH = {"check", "run"}


def parse(argv):
    """Parse `argv`; `check` and `run` collect the arguments they don't know into `args.extra`."""
    parser = build_parser()
    args, extra = parser.parse_known_args(argv)
    if extra and args.command not in PASSTHROUGH:
        parser.error(f"unrecognized arguments: {' '.join(extra)}")
    args.extra = extra[1:] if extra[:1] == ["--"] else extra
    return args


def plan(args, root, cwd):
    """The (argv, cwd) to run for parsed `args`."""
    if args.command == "test":
        verbose = ["-v"] if args.verbose else []
        patterns = [arg for pattern in args.patterns for arg in ("-k", pattern)]
        return [sys.executable, "-m", "unittest", "discover", "-s", "tests", *verbose, *patterns], root
    if args.command == "check":
        return ["nix", "flake", "check", *args.extra], root
    if args.command == "fmt":
        return ["nix", "fmt"], root
    if args.command == "run":
        return [sys.executable, os.path.join(root, COMMAND), *args.extra], cwd
    raise ValueError(f"unknown command: {args.command}")


def untracked_warning(paths):
    """The warning for untracked files `nix flake check` won't see, or None."""
    if not paths:
        return None
    listed = "".join(f"  {path}\n" for path in paths)
    return f"warning: nix flake check ignores these untracked files; stage them with git add:\n{listed}"


def untracked_files(root):
    result = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    return result.stdout.splitlines() if result.returncode == 0 else []


def main(argv=None, root=ROOT, run=subprocess.call):
    args = parse(argv)
    if args.command == "check":
        warning = untracked_warning(untracked_files(root))
        if warning:
            sys.stderr.write(warning)
    command, cwd = plan(args, root, os.getcwd())
    try:
        return run(command, cwd=cwd)
    except FileNotFoundError as error:
        sys.stderr.write(f"nix-jetbrains-project-setup-dev: {error.filename}: not found\n")
        return 127


if __name__ == "__main__":
    sys.exit(main())
