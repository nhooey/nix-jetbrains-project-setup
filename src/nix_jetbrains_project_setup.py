#!/usr/bin/env python3
"""Set up JetBrains IDEs for Nix projects without touching version control.

Per-project state goes only into `.idea/` and `.nix/sdk/`; IDE-wide state is a
marked block in each IDE's user `.vmoptions` file. Every run computes the
desired state from the config and reconciles it against a manifest of what
this tool owns. A change made in the IDE to an owned entry wins: it is
recorded as an opt-out and reported by `--check --json`.
"""

import argparse
import difflib
import fnmatch
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

NAME = "nix-jetbrains-project-setup"
MANIFEST = NAME + ".manifest.json"
BEGIN = "# BEGIN " + NAME
END = "# END " + NAME
# Every config key with its default; it ships next to this script.
DEFAULTS_FILE = os.path.join(os.path.dirname(os.path.realpath(__file__)), "defaults.json")
# The keys a `projects` entry may set, over the global ones.
PROJECT_KEYS = ("excludeFolders", "excludePatterns", "sdks")
# The kind of each entry in a config key's object or list: on/off sets hold
# booleans, `sdks` installables and `removeJvmOptions` globs.
ENTRY_KINDS = {
    "excludeFolders": bool,
    "excludePatterns": bool,
    "sdks": str,
    "jvmOptions": bool,
    "removeJvmOptions": str,
}
# IDE config dir prefix -> launcher name, used for `<name>.vmoptions`.
PRODUCTS = {
    "IntelliJIdea": "idea",
    "IdeaIC": "idea",
    "PyCharm": "pycharm",
    "PyCharmCE": "pycharm",
    "CLion": "clion",
    "Rider": "rider",
    "GoLand": "goland",
    "WebStorm": "webstorm",
    "PhpStorm": "phpstorm",
    "RubyMine": "rubymine",
    "DataGrip": "datagrip",
    "DataSpell": "dataspell",
    "RustRover": "rustrover",
    "Aqua": "aqua",
    "JetBrainsGateway": "gateway",
}
IDE_DIR_RE = re.compile(r"^([A-Za-z]+)(\d{4}\.\d+)$")
MODULES_XML = """<?xml version="1.0" encoding="UTF-8"?>
<project version="4">
  <component name="ProjectModuleManager">
    <modules>
      <module fileurl="file://$PROJECT_DIR$/.idea/{name}.iml" filepath="$PROJECT_DIR$/.idea/{name}.iml" />
    </modules>
  </component>
</project>"""
IML_XML = """<?xml version="1.0" encoding="UTF-8"?>
<module type="JAVA_MODULE" version="4">
  <component name="NewModuleRootManager" inherit-compiler-output="true">
    <exclude-output />
    <content url="file://$MODULE_DIR$" />
    <orderEntry type="inheritedJdk" />
    <orderEntry type="sourceFolder" forTests="false" />
  </component>
</module>"""


def warn(msg):
    print(f"{NAME}: warning: {msg}", file=sys.stderr)


def nix_attr(key):
    """Quote an attribute name the way Nix would need it in an attr path."""
    return key if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_'-]*", key) else json.dumps(key)


def tilde(path):
    home = os.path.realpath(os.path.expanduser("~"))
    if path == home or path.startswith(home + os.sep):
        return "~" + path[len(home) :]
    return path


def read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def dump_json(data):
    return (json.dumps(data, indent=2, sort_keys=True) + "\n").encode()


def new_file_mode():
    umask = os.umask(0)
    os.umask(umask)
    rw_all = stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP
    return (rw_all | stat.S_IROTH | stat.S_IWOTH) & ~umask


class Run:
    """One invocation: collects what changed (or would) and the GUI drift."""

    def __init__(self, dry):
        self.dry = dry
        self.changes = []
        self.drift = []
        self.failed = False

    def write(self, path, data):
        """Write `data` atomically, and only if the bytes on disk differ."""
        try:
            with open(path, "rb") as f:
                old = f.read()
        except FileNotFoundError:
            old = None
        if old == data:
            return
        self.changes.append(tilde(path))
        if self.dry:
            return
        directory = os.path.dirname(path)
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, prefix="." + os.path.basename(path) + ".")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            if old is None:
                os.chmod(tmp, new_file_mode())
            else:
                shutil.copymode(path, tmp)
            os.replace(tmp, path)
        except BaseException:
            os.unlink(tmp)
            raise


def reconcile(desired, owned, present, optouts, source, block):
    """Reconcile one on/off attribute set against what a file holds.

    desired: {key: bool} from config; owned: keys this tool wrote last time;
    present: keys in the file now; optouts: {key: record} from the manifest.
    With `block`, every key present is inside the tool's own block, so an
    unowned one was added in the GUI; otherwise unowned keys are the user's
    and are ignored. Returns (add, remove, owned, optouts).
    """

    def want(k):
        return bool(desired.get(k, False))

    kept = {}
    for k, rec in optouts.items():
        # An opt-out lasts while the file still shows the GUI's choice and
        # the config still disagrees with it.
        if (k in present) == rec["value"] and want(k) != rec["value"]:
            kept[k] = rec
    for k in owned:
        if k not in present and want(k):
            kept[k] = {"value": False, "was": True, "source": source}
    if block:
        for k in present:
            if k not in owned and not want(k):
                kept.setdefault(k, {"value": True, "was": False, "source": source})
    add = [k for k, v in desired.items() if v and k not in present and k not in kept]
    remove = [k for k in owned if k in present and not want(k)]
    if block:
        new_owned = [k for k in present if want(k)] + add
    else:
        new_owned = [k for k in owned if k in present and want(k)] + add
    return add, remove, new_owned, kept


# ----------------------------------------------------------------- config


class ConfigError(Exception):
    pass


def load_defaults():
    with open(DEFAULTS_FILE) as f:
        return json.load(f)


def load_config(path):
    """The shipped defaults with the user's config file, if any, merged over them."""
    defaults = load_defaults()
    if path is None:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        path = os.path.join(base, NAME, "config.json")
        if not os.path.exists(path):
            return defaults
    with open(path) as f:
        user = json.load(f)
    check_config(user, defaults, tilde(path))
    return merged(defaults, user)


def check_config(user, defaults, where):
    """Refuse unknown keys and values that aren't the default's kind."""

    def check(cfg, known, where):
        if not isinstance(cfg, dict):
            raise ConfigError(f"{where}: expected an object")
        for key, value in cfg.items():
            if key not in known:
                close = difflib.get_close_matches(key, known, n=1)
                hint = f" (did you mean {close[0]!r}?)" if close else ""
                raise ConfigError(f"{where}: unknown key {key!r}{hint}")
            if type(value) is not type(defaults[key]):
                kinds = (type(defaults[key]).__name__, type(value).__name__)
                raise ConfigError(f"{where}: {key} must be %s, not %s" % kinds)
            kind = ENTRY_KINDS.get(key)
            entries = value.items() if isinstance(value, dict) else enumerate(value)
            for name, entry in entries if kind else ():
                if type(entry) is not kind:
                    at = f"{key}.{json.dumps(name)}" if isinstance(value, dict) else f"{key}[{name}]"
                    raise ConfigError(f"{where}: {at} must be {kind.__name__}, not {type(entry).__name__}")

    check(user, list(defaults), where)
    for path, pcfg in merged(defaults, user)["projects"].items():
        check(pcfg, PROJECT_KEYS, f"{where}: projects.{json.dumps(path)}")


def merged(a, b):
    """b over a: objects merge key by key at every level; anything else replaces."""
    out = dict(a)
    for k, v in b.items():
        out[k] = merged(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def project_settings(cfg, root):
    settings = {k: cfg[k] for k in PROJECT_KEYS}
    for path, pcfg in cfg["projects"].items():
        if os.path.realpath(os.path.expanduser(path)) == root:
            settings = merged(settings, pcfg)
    return settings


# ---------------------------------------------------------------- project


def git(root, *args):
    try:
        return subprocess.run(["git", "-C", root, *args], capture_output=True).returncode
    except FileNotFoundError:
        return None


def parse_xml(data):
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    return ET.fromstring(data, parser=parser)


def serialize_xml(elem, trailing_newline):
    ET.indent(elem, "  ")
    text = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(elem, encoding="unicode")
    return (text + ("\n" if trailing_newline else "")).encode()


def module_dir(iml_path, root):
    # IntelliJ resolves $MODULE_DIR$ to the project root for an iml in .idea/.
    parent = os.path.dirname(iml_path)
    return root if parent == os.path.join(root, ".idea") else parent


def find_content(iml, iml_path, root):
    mdir = module_dir(iml_path, root)
    for comp in iml.iter("component"):
        if comp.get("name") != "NewModuleRootManager":
            continue
        for content in comp.findall("content"):
            url = content.get("url", "")
            if url.startswith("file://"):
                path = url[len("file://") :].replace("$MODULE_DIR$", mdir)
                if os.path.normpath(path) == root:
                    return content
    return None


def find_iml(root):
    modules = os.path.join(root, ".idea", "modules.xml")
    if not os.path.exists(modules):
        return None
    with open(modules, "rb") as f:
        project = parse_xml(f.read())
    for module in project.iter("module"):
        path = module.get("filepath", "").replace("$PROJECT_DIR$", root)
        if os.path.exists(path):
            with open(path, "rb") as f:
                data = f.read()
            iml = parse_xml(data)
            if find_content(iml, path, root) is not None:
                return path, iml, data.endswith(b"\n")
    return None


def insert_after(parent, elem, after_tags):
    index = 0
    for i, child in enumerate(list(parent)):
        if child.tag in after_tags:
            index = i + 1
    parent.insert(index, elem)


def reconcile_excludes(run, root, settings, manifest, in_git):
    idea = os.path.join(root, ".idea")
    bootstrap = not os.path.exists(idea)
    if bootstrap:
        name = os.path.basename(root)
        iml_path = os.path.join(idea, name + ".iml")
        iml, trailing = parse_xml(IML_XML), True
        manifest["bootstrapped"] = [".idea/modules.xml", f".idea/{name}.iml"]
    else:
        found = find_iml(root)
        if found is None:
            warn(f"{tilde(root)}: no module in .idea/modules.xml has the project root as content; skipping excludes")
            return
        iml_path, iml, trailing = found
        rel = os.path.relpath(iml_path, root)
        if in_git and git(root, "ls-files", "--error-unmatch", "--", rel) == 0:
            warn(f"{tilde(root)}: {rel} is tracked in git; not modifying it")
            return
    content = find_content(iml, iml_path, root)
    curl = content.get("url").rstrip("/")
    source = os.path.basename(iml_path)
    optouts = manifest.setdefault("optOuts", {})
    changed = False
    kinds = (
        ("excludeFolders", "excludeFolder", "url", ("sourceFolder", "excludeFolder")),
        ("excludePatterns", "excludePattern", "pattern", ("sourceFolder", "excludeFolder", "excludePattern")),
    )
    for kind, tag, attr, after in kinds:
        elems = {}
        for el in content.findall(tag):
            value = el.get(attr, "")
            if kind == "excludePatterns":
                elems[value] = el
            elif value.startswith(curl + "/"):
                elems[value[len(curl) + 1 :]] = el
        before = optouts.get(kind, {})
        add, remove, owned, kept = reconcile(
            settings[kind], manifest.get(kind, []), list(elems), before, source, block=False
        )
        for key, rec in kept.items():
            path = f"{kind}.{nix_attr(key)}"
            run.drift.append({"project": tilde(root), "path": path, **rec})
            if key not in before and not run.dry:
                warn(f"{tilde(root)}: {path} was changed in the IDE; leaving it (see --check --json)")
        for key in remove:
            content.remove(elems[key])
        for key in add:
            value = curl + "/" + key if kind == "excludeFolders" else key
            insert_after(content, ET.Element(tag, {attr: value}), after)
        changed = changed or bool(add or remove)
        manifest[kind], optouts[kind] = owned, kept
    if bootstrap:
        run.write(os.path.join(idea, "modules.xml"), MODULES_XML.format(name=name).encode() + b"\n")
    if bootstrap or changed:
        run.write(iml_path, serialize_xml(iml, trailing))


def reconcile_sdks(run, root, sdks, manifest, rebuild):
    nix = os.environ.get("NIX_JETBRAINS_PROJECT_SETUP_NIX", "nix")
    owned = manifest.get("sdks", {})
    sdk_dir = os.path.join(root, ".nix", "sdk")
    result = {}
    for name, installable in sdks.items():
        link = os.path.join(sdk_dir, name)
        if "/" in name or name in ("", ".", ".."):
            warn(f"{tilde(root)}: invalid SDK name {name!r}")
            continue
        if name not in owned and os.path.lexists(link):
            warn(f"{tilde(root)}: {tilde(link)} exists and was not made by {NAME}; leaving it")
            continue
        if os.path.exists(link) and owned.get(name) == installable and not rebuild:
            result[name] = installable
            continue
        run.changes.append(f"nix build --out-link {tilde(link)} {installable}")
        if not run.dry:
            os.makedirs(sdk_dir, exist_ok=True)
            if subprocess.run([nix, "build", "--out-link", link, installable]).returncode != 0:
                warn(f"{tilde(root)}: nix build {installable} failed")
                run.failed = True
                if name in owned:
                    result[name] = owned[name]
                continue
        result[name] = installable
    for name in owned:
        link = os.path.join(sdk_dir, name)
        if name not in sdks and os.path.islink(link):
            run.changes.append(f"remove {tilde(link)}")
            if not run.dry:
                os.unlink(link)
    manifest["sdks"] = result


def apply_project(run, cfg, path, rebuild_sdks):
    root = os.path.realpath(os.path.expanduser(path))
    if not os.path.isdir(root):
        warn(f"{tilde(root)}: not a directory; skipping")
        run.failed = True
        return
    settings = project_settings(cfg, root)
    manifest_path = os.path.join(root, ".idea", MANIFEST)
    manifest = read_json(manifest_path)
    in_git = git(root, "rev-parse", "--is-inside-work-tree") == 0
    if in_git:
        if git(root, "check-ignore", "-q", ".idea") != 0:
            warn(f"{tilde(root)}: .idea is not git-ignored; collaborators would see it")
        if settings["sdks"] and git(root, "check-ignore", "-q", ".nix/sdk/x") != 0:
            warn(f"{tilde(root)}: .nix/sdk is not git-ignored; collaborators would see it")
    reconcile_excludes(run, root, settings, manifest, in_git)
    reconcile_sdks(run, root, settings["sdks"], manifest, rebuild_sdks)
    manifest = {k: v for k, v in manifest.items() if v}
    if "optOuts" in manifest:
        manifest["optOuts"] = {k: v for k, v in manifest["optOuts"].items() if v} or None
        if manifest["optOuts"] is None:
            del manifest["optOuts"]
    if manifest or os.path.exists(manifest_path):
        run.write(manifest_path, dump_json({"version": 1, **manifest}))


# -------------------------------------------------------------------- jvm


def jetbrains_dir():
    override = os.environ.get("NIX_JETBRAINS_PROJECT_SETUP_JETBRAINS_DIR")
    if override:
        return override
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/JetBrains")
    return os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "JetBrains")


def state_dir():
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, NAME)


def vmoptions_name(ide_dir, product):
    names = sorted(f for f in os.listdir(ide_dir) if f.endswith(".vmoptions"))
    for candidate in (f"{product}.vmoptions", f"{product}64.vmoptions"):
        if candidate in names:
            return candidate
    if names:
        return names[0]
    return f"{product}.vmoptions" if product else None


def apply_ide(run, ide, path, state, desired, removes):
    """Reconcile one IDE's vmoptions file; returns its new manifest state."""
    fname = os.path.basename(path)
    exists = os.path.exists(path)
    text = ""
    if exists:
        with open(path) as f:
            text = f.read()
    lines = text.splitlines()
    begin = end = None
    if BEGIN in lines:
        begin = lines.index(BEGIN)
        if END not in lines[begin + 1 :]:
            warn(f"{ide}: {fname} has '{BEGIN}' but no '{END}'; skipping")
            return state
        end = lines.index(END, begin + 1)
        block = [ln.strip() for ln in lines[begin + 1 : end] if ln.strip() and not ln.strip().startswith("#")]
        pre, post = lines[:begin], lines[end + 1 :]
    else:
        block, pre, post = [], lines, []
    add, remove, owned, kept = reconcile(
        desired, state.get("jvmOptions", []), block, state.get("optOuts", {}), fname, block=True
    )
    for key, rec in kept.items():
        path_ = f"jvmOptions.{nix_attr(key)}"
        run.drift.append({"ide": ide, "path": path_, **rec})
        if key not in state.get("optOuts", {}) and not run.dry:
            warn(f"{ide}: {path_} was changed in the IDE; leaving it (see --check --json)")

    def removable(line):
        s = line.strip()
        return bool(s) and any(fnmatch.fnmatchcase(s, p) for p in removes)

    removed = [ln.strip() for ln in pre + post if removable(ln)]
    pre = [ln for ln in pre if not removable(ln)]
    post = [ln for ln in post if not removable(ln)]
    new_block = [ln for ln in block if ln not in remove] + add
    marked = [BEGIN, *new_block, END] if new_block else []
    out = pre + marked + post
    trailing = text.endswith("\n") or (begin is None and bool(marked)) or not text
    new_text = "\n".join(out) + ("\n" if out and trailing else "")
    created = state.get("created", False) or (not exists and bool(new_text))
    if created and exists and not new_text.strip():
        run.changes.append(f"remove {tilde(path)}")
        if not run.dry:
            os.unlink(path)
        created = False
    elif new_text != text:
        run.write(path, new_text.encode())
    new_state = {
        "file": fname,
        "jvmOptions": owned,
        "optOuts": kept,
        "removed": sorted(set(state.get("removed", []) + removed)),
        "created": created,
    }
    return {k: v for k, v in new_state.items() if v}


def apply_jvm(run, cfg):
    base = jetbrains_dir()
    if not os.path.isdir(base):
        return
    manifest_path = os.path.join(state_dir(), "manifest.json")
    manifest = read_json(manifest_path)
    ides = manifest.get("ides", {})
    desired = cfg["jvmOptions"]
    removes = cfg["removeJvmOptions"]
    for ide in sorted(os.listdir(base)):
        match = IDE_DIR_RE.match(ide)
        ide_dir = os.path.join(base, ide)
        if not match or not os.path.isdir(ide_dir):
            continue
        state = ides.get(ide, {})
        fname = state.get("file") or vmoptions_name(ide_dir, PRODUCTS.get(match.group(1)))
        if fname is None:
            continue
        path = os.path.join(ide_dir, fname)
        if not os.path.exists(path) and not state and not any(desired.values()):
            continue
        new_state = apply_ide(run, ide, path, state, desired, removes)
        if new_state.keys() - {"file"}:
            ides[ide] = new_state
        else:
            ides.pop(ide, None)
    if ides or os.path.exists(manifest_path):
        run.write(manifest_path, dump_json({"version": 1, "ides": ides}))


# ------------------------------------------------------------------- main


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["apply"]:
        argv = argv[1:]
    parser = argparse.ArgumentParser(
        prog=NAME,
        usage=f"{NAME} [apply] [--check [--json]] [--jvm | --all] [options] [DIR ...]",
        description="Reconcile JetBrains project excludes, Nix SDK links and IDE JVM options with the config.",
    )
    parser.add_argument("dirs", nargs="*", metavar="DIR", help="project directories (default: the current one)")
    parser.add_argument("--config", help="config JSON (default: $XDG_CONFIG_HOME/%s/config.json)" % NAME)
    parser.add_argument(
        "--check", action="store_true", help="change nothing; exit 1 on drift, opt-outs or pending changes"
    )
    parser.add_argument("--json", action="store_true", help="with --check, print the GUI changes as a JSON array")
    parser.add_argument(
        "--jvm", action="store_true", help="reconcile JVM options of every installed IDE (with no DIR, only those)"
    )
    parser.add_argument("--all", action="store_true", help="every project in the config, plus JVM options")
    parser.add_argument("--rebuild-sdks", action="store_true", help="rebuild SDK links even when present")
    args = parser.parse_args(argv)
    if args.json and not args.check:
        parser.error("--json requires --check")

    try:
        cfg = load_config(args.config)
    except ConfigError as e:
        print(f"{NAME}: error: {e}", file=sys.stderr)
        return 2
    run = Run(dry=args.check)
    dirs = list(args.dirs)
    if args.all:
        dirs += list(cfg["projects"])
    elif not dirs and not args.jvm:
        dirs = ["."]
    for d in dirs:
        apply_project(run, cfg, d, args.rebuild_sdks)
    if args.jvm or args.all:
        apply_jvm(run, cfg)

    if args.json:
        print(json.dumps(run.drift, indent=2))
    elif args.check:
        for change in run.changes:
            print(f"would update: {change}")
        for d in run.drift:
            where = d.get("project") or d.get("ide")
            print(
                f"changed in the IDE: {where}: {d['path']} = {json.dumps(d['value'])} (config: {json.dumps(d['was'])})"
            )
    else:
        for change in run.changes:
            print(f"updated: {change}")
    if run.failed:
        return 2
    if args.check and (run.changes or run.drift):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
