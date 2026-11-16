# nix-jetbrains-project-setup

Sets up JetBrains IDEs (IntelliJ IDEA, PyCharm, CLion, Rider, …) for Nix
projects without touching the project's version control, so collaborators
never need to know.

- **Per project**, it excludes Nix clutter (`.direnv`, `.nix`, `result`,
  `result-*`) in the module's `.iml`, and builds configured SDKs as Nix
  out-links under `.nix/sdk/<name>`. It writes only into `.idea/` and
  `.nix/sdk/`, which your global git ignore should cover:

  ```gitignore
  /.idea
  *.iml
  /.nix/sdk/
  ```

- **For every installed IDE**, it keeps a marked block of JVM options in the
  IDE's user `.vmoptions` file.

It is declarative: each run computes the desired state from the config and
reconciles it. Running it again changes nothing, prompts nothing and never
fails on "already exists". A file is written only when its bytes would
change, so an open IDE gets no "reload project" prompt, and always
atomically.

## Install

- `nix profile install github:nhooey/nix-jetbrains-project-setup`
- Or the Home Manager module below.
- Or `nix run github:nhooey/nix-jetbrains-project-setup -- apply`.

## Use

```console
$ cd ~/git/nhooey/eventura && nix-jetbrains-project-setup apply
$ nix-jetbrains-project-setup apply --jvm      # JVM options of every IDE only
$ nix-jetbrains-project-setup apply --all      # every project in the config, plus JVM options
$ nix-jetbrains-project-setup --check --json   # report drift, change nothing
```

```
nix-jetbrains-project-setup [apply] [--check [--json]] [--jvm | --all] [--config FILE] [--rebuild-sdks] [DIR ...]
```

With no `DIR` it works on the current directory. `--check` exits 0 when
everything matches, 1 when a run would change something or there are GUI
changes not yet in the config, and 2 when something failed (such as a
`nix build`).

## What it owns, and what it leaves alone

It keeps a manifest of what it wrote: `.idea/nix-jetbrains-project-setup.manifest.json`
per project and `$XDG_STATE_HOME/nix-jetbrains-project-setup/manifest.json`
(default `~/.local/state/…`) for the IDEs. It adds desired entries that are
missing and removes only entries it added itself. An exclude you added in
the IDE is never touched, and one that already existed is not adopted.

- **Tracked files are never modified.** If the `.iml` is tracked in git, it
  is skipped with a warning. It warns, without editing `.gitignore`, when
  `.idea` (or `.nix/sdk`, with SDKs configured) isn't git-ignored. Outside a
  git repository it just works.
- **The module** comes from `.idea/modules.xml`: the first module whose
  `<content>` root is the project root. The `.iml` can sit at the root or in
  `.idea/` (where `$MODULE_DIR$` means the project root). Excludes are built
  from the content element's own URL, and the file keeps IntelliJ's format.
- **No `.idea` at all:** it creates a minimal `.idea/modules.xml` and
  `.idea/<dirname>.iml`. A `.idea` without `modules.xml` (Rider) is skipped.
- **SDKs:** `nix build --out-link <project>/.nix/sdk/<name> <installable>`,
  only when the link is missing or its installable changed
  (`--rebuild-sdks` forces it, e.g. after a flake update). The out-link is a
  GC root, so `nix-collect-garbage --delete-older-than 30d` keeps it. Links
  no longer configured are removed. `NIX_JETBRAINS_PROJECT_SETUP_NIX`
  overrides the `nix` command.
- **JVM options:** each IDE config dir under
  `~/Library/Application Support/JetBrains/<Product><Version>/` (Linux:
  `~/.config/JetBrains/`; override with `NIX_JETBRAINS_PROJECT_SETUP_JETBRAINS_DIR`)
  gets this block in `<product>.vmoptions` (or `<product>64.vmoptions`):

  ```
  # BEGIN nix-jetbrains-project-setup
  -XX:+UseG1GC
  # END nix-jetbrains-project-setup
  ```

  Every other line stays, notably `-Xmx` from Help → Change Memory Settings
  and the JetBrains Toolbox `-D` lines. `removeJvmOptions` is the opt-in list
  of lines outside the block to delete; they are recorded in the IDE
  manifest. `<PRODUCT>_VM_OPTIONS` variables are not used, since their
  precedence over the user file isn't clearly documented.

## The GUI wins

If you change or remove an entry the tool owns in the IDE (say you
un-exclude `result` in Project Structure, or edit a line inside the
vmoptions block), the next run records it as an **opt-out** and leaves it
alone from then on; it never restores it. A line added inside the block in
the IDE is kept the same way. An opt-out clears itself once the config
agrees with it, e.g. once the config says `excludePatterns.result = false`.

## Config

JSON at `$XDG_CONFIG_HOME/nix-jetbrains-project-setup/config.json` (default
`~/.config/…`), or `--config FILE`. Every key and its default is in
[`src/defaults.json`](src/defaults.json), which is installed beside the
command and read on every run; your file names only what it changes, and
with no file the command runs on the defaults. Lists of things are on/off
attribute sets, so a GUI change can be written down as `false`:

```json
{
  "excludeFolders": { "target": true },
  "excludePatterns": { "*.log": true },
  "sdks": { "jdk": "nixpkgs#jdk21" },
  "jvmOptions": { "-XX:+UseG1GC": true },
  "removeJvmOptions": ["-XX:+UseConcMarkSweepGC", "-XX:+UseParNewGC", "-XX:+AggressiveOpts",
                       "-XX:CMSInitiatingOccupancyFraction=*"],
  "projects": {
    "~/git/nhooey/eventura": { "excludeFolders": { ".nix": false }, "sdks": { "python": "nixpkgs#python3" } }
  }
}
```

| Key | Scope | Meaning |
|---|---|---|
| `excludeFolders` | global, project | Folder (relative to the content root) → excluded. Defaults: `.direnv`, `.nix`. |
| `excludePatterns` | global, project | Exclude pattern → on. Defaults: `result`, `result-*`. |
| `sdks` | global, project | Name → Nix installable, linked at `.nix/sdk/<name>`. |
| `jvmOptions` | global | JVM option line → kept in the managed block. |
| `removeJvmOptions` | global | Lines outside the block to delete (shell-style globs). |
| `projects` | global | Path (`~` allowed) → per-project keys. |

Settings merge in order defaults → global → project; attribute sets merge
key by key at every level and the later one wins, and a list replaces the
earlier one whole. An unknown key, a project-scoped entry with a global-only
key, or a value of the wrong kind is an error (exit 2) and nothing is changed.

## Drift report, for an agent to fold back into Nix

`--check --json` prints one object per GUI change, keyed by the config path
it corresponds to:

```json
[
  {"project": "~/git/nhooey/eventura", "path": "excludePatterns.result", "value": false, "was": true, "source": "eventura.iml"},
  {"ide": "IntelliJIdea2026.2", "path": "jvmOptions.\"-Xmx4096m\"", "value": false, "was": true, "source": "idea.vmoptions"}
]
```

- `project` (the project path, `~`-relative) or `ide` (the config dir name)
  says where the change is.
- `path` is the Nix attribute path within that scope, quoted the way Nix
  needs it. For a `project` entry it goes under
  `programs.nix-jetbrains-project-setup.projects."<project>"` (or at the
  top level, if the change should apply to every project); for an `ide`
  entry, at the top level (`jvmOptions` is global).
- `value` is what the IDE now has, `was` what the tool had written.
  `"value": true, "was": false` is a line added inside the block in the IDE.
- `source` is the file the change was found in.

An agent folds each object into the user's MyNixOS / Home Manager settings
by setting `path` to `value`, e.g.
`programs.nix-jetbrains-project-setup.projects."~/git/nhooey/eventura".excludePatterns.result = false;`.
After the switch, the next run sees the config agree with the GUI and clears
the opt-outs; `--check` then exits 0.

## Home Manager module

```nix
{
  imports = [ inputs.nix-jetbrains-project-setup.homeModules.default ];
  # or inputs.nur-packages.homeModules.nix-jetbrains-project-setup

  programs.nix-jetbrains-project-setup = {
    enable = true;
    excludeFolders.target = true;
    jvmOptions."-XX:+UseG1GC" = true;
    removeJvmOptions = [ "-XX:+UseConcMarkSweepGC" ];
    projects."~/git/nhooey/eventura".sdks.jdk = "nixpkgs#jdk21";
    # runOnActivation = true;  # default
  };
}
```

Options: `enable`, `package`, `excludeFolders`, `excludePatterns`, `sdks`,
`jvmOptions`, `removeJvmOptions`, `projects` (each with `excludeFolders`,
`excludePatterns`, `sdks`) and `runOnActivation`. The module writes the
config JSON with `xdg.configFile`. It never links IDE files from the store;
the command merges into them.

## When it runs

- **By hand**, `nix-jetbrains-project-setup apply` in a project.
- **On Home Manager activation** (`runOnActivation`, on by default):
  `apply --all` for every listed project and the JVM options. A failure
  only prints a warning.
- **From a direnv hook.** direnv sources `~/.config/direnv/direnvrc`
  before every `.envrc`, so a few lines there cover every direnv project
  without editing any project's (possibly tracked) `.envrc`. Not installed
  for you:

  ```bash
  # Projects already opened in a JetBrains IDE only, so others get no .idea.
  if [[ -d .idea ]] && has nix-jetbrains-project-setup; then
    nix-jetbrains-project-setup apply "$PWD" >&2 || true
  fi
  ```

  Unchanged files are never rewritten, so this costs a few milliseconds.
