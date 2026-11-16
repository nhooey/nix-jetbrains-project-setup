# Working on this repository

`src/nix_jetbrains_project_setup.py` is the whole command: Python 3,
standard library only. `package.nix` installs it as
`bin/nix-jetbrains-project-setup` and runs the tests in its `checkPhase`;
`nix/home-module.nix` is the Home Manager module (`homeModules.default`).
`README.md` describes the behavior, the config and the drift JSON.
Plans live in `agents/plans/` (skill `coding-agent-plans-as-graph`).

## Checks

There is no CI. The dev shell's `nix-jetbrains-project-setup-dev`
(`dev/nix_jetbrains_project_setup_dev.py`, in its menu) runs them; each
token has `--help`. Before committing, run:

- `nix-jetbrains-project-setup-dev check`: formatting (nixfmt, ruff), the
  package build, which runs the unittest suite, and
  `nix/home-module-test.nix`, which evaluates the Home Manager module
  against stub options. Stage new files first, since Nix only sees tracked
  ones; it warns about untracked files.
- `nix-jetbrains-project-setup-dev test [-v] [-k PATTERN]` for a quick run,
  and `nix-jetbrains-project-setup-dev fmt` to format.
  `nix-jetbrains-project-setup-dev run ARG ...` runs the command from the
  checkout, on real files. `tests/support.py` holds the temp-dir fixtures,
  `test_units.py` the pure functions, `test_dev.py` the dev tool, and the
  other modules drive `main()` end to end.

## Rules

- **Tests never touch real IDE or project files.** Every test points
  `HOME`, the XDG dirs, `NIX_JETBRAINS_PROJECT_SETUP_JETBRAINS_DIR` and
  `NIX_JETBRAINS_PROJECT_SETUP_NIX` (a stub) into a temp dir.
- **Idempotence is the contract.** A second run must leave every file's
  bytes and mtime unchanged; add a no-op assertion to any new reconciler.
- **The GUI wins.** Never restore an owned entry the user changed in the
  IDE; record an opt-out instead (`reconcile()`).
- **A change to the drift JSON** is a change to the agent-facing interface:
  update the README section with it.

## Conventions

- **Branches and commits:** the default branch is `master`; commit messages
  follow Conventional Commits (skill `git-hygiene-conventional-commits`).
