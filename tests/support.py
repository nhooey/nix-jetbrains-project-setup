"""Shared fixtures for the nix-jetbrains-project-setup tests.

`Base` runs every test in a temp dir: HOME, the XDG dirs, the JetBrains
config base and `nix` (a stub) all point into it, so no test can touch a
real IDE or project file."""

import contextlib
import io
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import nix_jetbrains_project_setup as njps  # noqa: E402

MODULES_XML = """<?xml version="1.0" encoding="UTF-8"?>
<project version="4">
  <component name="ProjectModuleManager">
    <modules>
      <module fileurl="file://$PROJECT_DIR$/{iml}" filepath="$PROJECT_DIR$/{iml}" />
    </modules>
  </component>
</project>
"""

IML = """<?xml version="1.0" encoding="UTF-8"?>
<module type="JAVA_MODULE" version="4">
  <component name="NewModuleRootManager" inherit-compiler-output="true">
    <exclude-output />
    <content url="file://$MODULE_DIR$" />
    <orderEntry type="inheritedJdk" />
    <orderEntry type="sourceFolder" forTests="false" />
  </component>
</module>
"""

APPLIED_IML = """<?xml version="1.0" encoding="UTF-8"?>
<module type="JAVA_MODULE" version="4">
  <component name="NewModuleRootManager" inherit-compiler-output="true">
    <exclude-output />
    <content url="file://$MODULE_DIR$">
      <excludeFolder url="file://$MODULE_DIR$/.direnv" />
      <excludeFolder url="file://$MODULE_DIR$/.nix" />
      <excludePattern pattern="result" />
      <excludePattern pattern="result-*" />
    </content>
    <orderEntry type="inheritedJdk" />
    <orderEntry type="sourceFolder" forTests="false" />
  </component>
</module>
"""

NIX_STUB = """#!{python}
import os, sys
log, store = os.environ["STUB_NIX_LOG"], os.environ["STUB_NIX_STORE"]
with open(log, "a") as f:
    f.write(" ".join(sys.argv[1:]) + "\\n")
args = sys.argv[1:]
if os.environ.get("STUB_NIX_FAIL"):
    sys.exit(1)
link, installable = args[args.index("--out-link") + 1], args[-1]
target = os.path.join(store, installable.replace("/", "_").replace("#", "_"))
os.makedirs(target, exist_ok=True)
if os.path.lexists(link):
    os.unlink(link)
os.symlink(target, link)
"""

VMOPTIONS = """# custom IntelliJ IDEA VM options
-server
-XX:+UseParNewGC
-XX:+AggressiveOpts
-XX:CMSInitiatingOccupancyFraction=65
#  -XX:+UseConcMarkSweepGC
-Xmx4096m
-Dide.managed.by.toolbox=/Applications/JetBrains Toolbox.app/Contents/MacOS/jetbrains-toolbox"""


class Base(unittest.TestCase):
    """Isolates a test from the real HOME; `cli()` drives main() end to end."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="njps-test-"))
        self.addCleanup(shutil.rmtree, self.tmp)
        self.home = os.path.join(self.tmp, "home")
        self.jetbrains = os.path.join(self.tmp, "JetBrains")
        os.makedirs(self.home)
        stub = os.path.join(self.tmp, "nix")
        with open(stub, "w") as f:
            f.write(NIX_STUB.format(python=sys.executable))
        os.chmod(stub, os.stat(stub).st_mode | stat.S_IXUSR)
        self.nix_log = os.path.join(self.tmp, "nix.log")
        env = {
            "HOME": self.home,
            "XDG_CONFIG_HOME": os.path.join(self.home, ".config"),
            "XDG_STATE_HOME": os.path.join(self.home, ".local", "state"),
            "NIX_JETBRAINS_PROJECT_SETUP_JETBRAINS_DIR": self.jetbrains,
            "NIX_JETBRAINS_PROJECT_SETUP_NIX": stub,
            "STUB_NIX_LOG": self.nix_log,
            "STUB_NIX_STORE": os.path.join(self.tmp, "store"),
            "GIT_CONFIG_GLOBAL": os.path.join(self.tmp, "gitconfig"),
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.config({})

    def config(self, cfg):
        path = os.path.join(self.home, ".config", njps.NAME, "config.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(cfg, f)

    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = njps.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def project(self, name="proj", iml_in_idea=False):
        root = os.path.join(self.home, name)
        os.makedirs(os.path.join(root, ".idea"))
        iml = f".idea/{name}.iml" if iml_in_idea else f"{name}.iml"
        self.put(root, ".idea/modules.xml", MODULES_XML.format(iml=iml))
        self.put(root, iml, IML)
        self.iml = os.path.join(root, iml)
        return root

    def put(self, root, rel, text):
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def read(self, path):
        with open(path) as f:
            return f.read()

    def manifest(self, root):
        return json.loads(self.read(os.path.join(root, ".idea", njps.MANIFEST)))

    def snapshot(self, root):
        snap = {}
        for dirpath, _, files in os.walk(root):
            for name in files:
                path = os.path.join(dirpath, name)
                with open(path, "rb") as f:
                    snap[path] = (f.read(), os.stat(path).st_mtime_ns)
        return snap

    def remove_line(self, path, needle):
        text = self.read(path)
        with open(path, "w") as f:
            f.write("".join(ln for ln in text.splitlines(True) if needle not in ln))
