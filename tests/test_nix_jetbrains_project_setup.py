"""Tests for nix-jetbrains-project-setup. Everything runs in a temp dir:
HOME, the XDG dirs, the JetBrains config base and `nix` all point into it."""

import contextlib
import io
import json
import os
import shutil
import stat
import subprocess
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


class ExcludeTests(Base):
    def test_first_apply(self):
        root = self.project()
        self.assertEqual(self.cli(root)[0], 0)
        self.assertEqual(self.read(self.iml), APPLIED_IML)
        m = self.manifest(root)
        self.assertEqual(m["excludeFolders"], [".direnv", ".nix"])
        self.assertEqual(m["excludePatterns"], ["result", "result-*"])

    def test_second_apply_is_a_noop(self):
        root = self.project()
        self.cli(root)
        before = self.snapshot(root)
        code, out, err = self.cli(root)
        self.assertEqual((code, out, err), (0, "", ""))
        self.assertEqual(self.snapshot(root), before)

    def test_user_excludes_untouched_and_not_adopted(self):
        root = self.project()
        user = IML.replace(
            '<content url="file://$MODULE_DIR$" />',
            '<content url="file://$MODULE_DIR$">\n'
            '      <excludeFolder url="file://$MODULE_DIR$/build" />\n'
            '      <excludeFolder url="file://$MODULE_DIR$/.direnv" />\n'
            "    </content>",
        )
        self.put(root, "proj.iml", user)
        self.cli(root)
        self.assertEqual(self.manifest(root)["excludeFolders"], [".nix"])
        # Turning .direnv off in config leaves the user's own entry alone.
        self.config({"excludeFolders": {".direnv": False}})
        self.cli(root)
        iml = self.read(self.iml)
        self.assertIn("$MODULE_DIR$/build", iml)
        self.assertIn("$MODULE_DIR$/.direnv", iml)

    def test_removing_from_config_removes_only_managed(self):
        root = self.project()
        self.cli(root)
        self.put(
            root,
            "proj.iml",
            self.read(self.iml).replace(
                '<excludePattern pattern="result" />',
                '<excludePattern pattern="result" />\n      <excludePattern pattern="*.log" />',
            ),
        )
        self.config({"excludePatterns": {"result-*": False}, "excludeFolders": {".nix": False}})
        self.cli(root)
        iml = self.read(self.iml)
        self.assertNotIn("result-*", iml)
        self.assertNotIn("$MODULE_DIR$/.nix", iml)
        self.assertIn("*.log", iml)
        self.assertIn("$MODULE_DIR$/.direnv", iml)
        self.assertEqual(self.manifest(root)["excludePatterns"], ["result"])

    def test_gui_removal_becomes_opt_out_and_clears(self):
        root = self.project()
        self.cli(root)
        self.remove_line(self.iml, 'pattern="result"')
        code, _, err = self.cli(root)
        self.assertEqual(code, 0)
        self.assertIn("excludePatterns.result was changed in the IDE", err)
        self.assertNotIn('pattern="result"', self.read(self.iml))
        self.assertIn("result", self.manifest(root)["optOuts"]["excludePatterns"])
        before = self.snapshot(root)
        self.cli(root)  # still not restored, nothing rewritten
        self.assertEqual(self.snapshot(root), before)
        self.assertEqual(self.cli("--check", root)[0], 1)
        # Config now agrees with the GUI: the opt-out clears.
        self.config({"excludePatterns": {"result": False}})
        self.cli(root)
        self.assertNotIn("optOuts", self.manifest(root))
        self.assertEqual(self.cli("--check", root)[0], 0)
        self.assertNotIn('pattern="result"', self.read(self.iml))

    def test_check_exit_codes_change_nothing(self):
        root = self.project()
        before = self.snapshot(root)
        code, out, _ = self.cli("apply", "--check", root)
        self.assertEqual(code, 1)
        self.assertIn("would update: ~/proj/proj.iml", out)
        self.assertEqual(self.snapshot(root), before)
        self.cli(root)
        self.assertEqual(self.cli("--check", root), (0, "", ""))

    def test_check_json(self):
        root = self.project()
        self.cli(root)
        self.remove_line(self.iml, ".direnv")
        code, out, _ = self.cli("--check", "--json", root)
        self.assertEqual(code, 1)
        self.assertEqual(
            json.loads(out),
            [
                {
                    "project": "~/proj",
                    "path": 'excludeFolders.".direnv"',
                    "value": False,
                    "was": True,
                    "source": "proj.iml",
                }
            ],
        )
        self.assertEqual(json.loads(self.cli("--check", "--json", root)[1])[0]["path"], 'excludeFolders.".direnv"')
        self.assertNotIn("optOuts", self.manifest(root))  # --check wrote nothing

    def test_per_project_config_merges(self):
        root = self.project()
        self.config(
            {
                "excludeFolders": {"target": True},
                "projects": {"~/proj": {"excludeFolders": {".nix": False, "out": True}}},
            }
        )
        self.cli(root)
        self.assertEqual(self.manifest(root)["excludeFolders"], [".direnv", "target", "out"])

    def test_tracked_iml_is_skipped(self):
        root = self.project()
        subprocess.run(["git", "init", "-q", root], check=True)
        subprocess.run(["git", "-C", root, "add", "proj.iml"], check=True)
        code, _, err = self.cli(root)
        self.assertEqual(code, 0)
        self.assertIn("proj.iml is tracked in git", err)
        self.assertIn(".idea is not git-ignored", err)
        self.assertEqual(self.read(self.iml), IML)

    def test_ignored_idea_gives_no_warning(self):
        root = self.project()
        subprocess.run(["git", "init", "-q", root], check=True)
        self.put(root, ".git/info/exclude", "/.idea\n*.iml\n")
        code, _, err = self.cli(root)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.read(self.iml), APPLIED_IML)

    def test_iml_inside_idea(self):
        root = self.project("temptask", iml_in_idea=True)
        self.cli(root)
        self.assertEqual(self.read(self.iml), APPLIED_IML)

    def test_bootstrap_without_idea(self):
        root = os.path.join(self.home, "fresh")
        os.makedirs(root)
        self.cli(root)
        self.assertEqual(self.read(os.path.join(root, ".idea", "fresh.iml")), APPLIED_IML)
        self.assertIn("$PROJECT_DIR$/.idea/fresh.iml", self.read(os.path.join(root, ".idea", "modules.xml")))
        self.assertEqual(self.manifest(root)["bootstrapped"], [".idea/modules.xml", ".idea/fresh.iml"])
        before = self.snapshot(root)
        self.assertEqual(self.cli(root), (0, "", ""))
        self.assertEqual(self.snapshot(root), before)


class SdkTests(Base):
    def test_create_and_remove_links(self):
        root = self.project()
        self.config({"sdks": {"jdk": "nixpkgs#jdk21", "python": "nixpkgs#python3"}})
        self.cli(root)
        link = os.path.join(root, ".nix", "sdk", "jdk")
        self.assertTrue(os.path.islink(link))
        self.assertEqual(self.manifest(root)["sdks"], {"jdk": "nixpkgs#jdk21", "python": "nixpkgs#python3"})
        self.cli(root)  # present and unchanged: no second build
        self.assertEqual(len(self.read(self.nix_log).splitlines()), 2)
        self.assertIn(f"build --out-link {link} nixpkgs#jdk21", self.read(self.nix_log))
        self.config({"sdks": {"python": "nixpkgs#python3"}})
        self.cli(root)
        self.assertFalse(os.path.lexists(link))
        self.assertTrue(os.path.islink(os.path.join(root, ".nix", "sdk", "python")))

    def test_foreign_link_left_alone(self):
        root = self.project()
        os.makedirs(os.path.join(root, ".nix", "sdk"))
        os.symlink("/nowhere", os.path.join(root, ".nix", "sdk", "jdk"))
        self.config({"sdks": {"jdk": "nixpkgs#jdk21"}})
        _, _, err = self.cli(root)
        self.assertIn("was not made by", err)
        self.assertEqual(os.readlink(os.path.join(root, ".nix", "sdk", "jdk")), "/nowhere")


class JvmTests(Base):
    def setUp(self):
        super().setUp()
        self.idea = os.path.join(self.jetbrains, "IntelliJIdea2026.2", "idea.vmoptions")
        os.makedirs(os.path.dirname(self.idea))
        with open(self.idea, "w") as f:
            f.write(VMOPTIONS)
        os.makedirs(os.path.join(self.jetbrains, "Rider2026.2"))
        os.makedirs(os.path.join(self.jetbrains, "Toolbox"))
        self.state = os.path.join(self.home, ".local", "state", njps.NAME, "manifest.json")

    def test_block_insert_update_and_noop(self):
        self.config({"jvmOptions": {"-XX:+UseG1GC": True, "-XX:+UseZGC": False}})
        self.assertEqual(self.cli("--jvm")[0], 0)
        expected = VMOPTIONS + f"\n{njps.BEGIN}\n-XX:+UseG1GC\n{njps.END}\n"
        self.assertEqual(self.read(self.idea), expected)
        rider = os.path.join(self.jetbrains, "Rider2026.2", "rider.vmoptions")
        self.assertEqual(self.read(rider), f"{njps.BEGIN}\n-XX:+UseG1GC\n{njps.END}\n")
        self.assertFalse(os.path.exists(os.path.join(self.jetbrains, "Toolbox", "toolbox.vmoptions")))
        before = self.snapshot(self.jetbrains)
        self.assertEqual(self.cli("--jvm"), (0, "", ""))
        self.assertEqual(self.snapshot(self.jetbrains), before)
        self.config({"jvmOptions": {"-XX:+UseG1GC": False, "-XX:SoftRefLRUPolicyMSPerMB=50": True}})
        self.cli("--jvm")
        self.assertEqual(
            self.read(self.idea), VMOPTIONS + f"\n{njps.BEGIN}\n-XX:SoftRefLRUPolicyMSPerMB=50\n{njps.END}\n"
        )
        # An empty config removes the block, and the file the tool created.
        self.config({})
        self.cli("--jvm")
        self.assertEqual(self.read(self.idea).rstrip("\n"), VMOPTIONS)
        self.assertFalse(os.path.exists(rider))

    def test_remove_jvm_options(self):
        self.config(
            {
                "removeJvmOptions": [
                    "-XX:+UseParNewGC",
                    "-XX:+AggressiveOpts",
                    "-XX:CMSInitiatingOccupancyFraction=*",
                    "-XX:+UseConcMarkSweepGC",
                ]
            }
        )
        self.cli("--jvm")
        text = self.read(self.idea)
        for gone in ("UseParNewGC", "AggressiveOpts", "CMSInitiatingOccupancyFraction"):
            self.assertNotIn(gone, text)
        for kept in ("-Xmx4096m", "-Dide.managed.by.toolbox", "#  -XX:+UseConcMarkSweepGC", "-server"):
            self.assertIn(kept, text)
        removed = json.loads(self.read(self.state))["ides"]["IntelliJIdea2026.2"]["removed"]
        self.assertEqual(removed, ["-XX:+AggressiveOpts", "-XX:+UseParNewGC", "-XX:CMSInitiatingOccupancyFraction=65"])

    def test_gui_edit_in_block_wins(self):
        self.config({"jvmOptions": {"-Xmx4096m": True, "-XX:+UseG1GC": True}})
        self.cli("--jvm")
        # Help > Change Memory Settings rewrites the -Xmx line inside the block.
        text = self.read(self.idea).replace(f"{njps.BEGIN}\n-Xmx4096m", f"{njps.BEGIN}\n-Xmx8192m")
        with open(self.idea, "w") as f:
            f.write(text)
        code, out, _ = self.cli("--check", "--json", "--jvm")
        self.assertEqual(code, 1)
        self.assertEqual(
            json.loads(out),
            [
                {
                    "ide": "IntelliJIdea2026.2",
                    "path": 'jvmOptions."-Xmx4096m"',
                    "value": False,
                    "was": True,
                    "source": "idea.vmoptions",
                },
                {
                    "ide": "IntelliJIdea2026.2",
                    "path": 'jvmOptions."-Xmx8192m"',
                    "value": True,
                    "was": False,
                    "source": "idea.vmoptions",
                },
            ],
        )
        self.cli("--jvm")
        self.assertEqual(self.read(self.idea), text)
        self.config({"jvmOptions": {"-Xmx4096m": False, "-Xmx8192m": True, "-XX:+UseG1GC": True}})
        self.cli("--jvm")
        self.assertEqual(self.read(self.idea), text)
        self.assertEqual(self.cli("--check", "--jvm"), (0, "", ""))


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
