"""End-to-end tests for one project: excludes in the .iml, SDK links in
.nix/sdk, and the per-project manifest."""

import json
import os
import subprocess
import unittest

from support import APPLIED_IML, IML, Base, njps


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

    def test_idea_without_modules_xml_is_skipped(self):
        # Rider's .idea layout has no modules.xml; nothing may be bootstrapped into it.
        root = os.path.join(self.home, "rider")
        os.makedirs(os.path.join(root, ".idea"))
        self.put(root, ".idea/workspace.xml", "<project />\n")
        before = self.snapshot(root)
        code, out, err = self.cli(root)
        self.assertEqual((code, out), (0, ""))
        self.assertIn("~/rider: no module in .idea/modules.xml has the project root as content", err)
        self.assertEqual(self.snapshot(root), before)

    def test_unignored_sdk_dir_warns(self):
        root = self.project()
        subprocess.run(["git", "init", "-q", root], check=True)
        self.put(root, ".git/info/exclude", "/.idea\n*.iml\n")
        self.config({"sdks": {"jdk": "nixpkgs#jdk21"}})
        _, _, err = self.cli(root)
        self.assertIn("~/proj: .nix/sdk is not git-ignored", err)
        self.assertNotIn(".idea is not git-ignored", err)
        self.put(root, ".git/info/exclude", "/.idea\n*.iml\n/.nix\n")
        self.assertEqual(self.cli(root), (0, "", ""))


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

    def builds(self):
        try:
            return self.read(self.nix_log).splitlines()
        except FileNotFoundError:
            return []

    def link(self, root, name="jdk"):
        return os.path.join(root, ".nix", "sdk", name)

    def test_rebuild_sdks_rebuilds_present_links(self):
        root = self.project()
        self.config({"sdks": {"jdk": "nixpkgs#jdk21"}})
        self.cli(root)
        code, out, _ = self.cli("--rebuild-sdks", root)
        self.assertEqual(code, 0)
        self.assertIn(f"updated: nix build --out-link ~/proj/.nix/sdk/jdk nixpkgs#jdk21", out)
        self.assertEqual(len(self.builds()), 2)

    def test_changed_installable_rebuilds_and_updates_manifest(self):
        root = self.project()
        self.config({"sdks": {"jdk": "nixpkgs#jdk21"}})
        self.cli(root)
        self.config({"sdks": {"jdk": "nixpkgs#jdk25"}})
        self.assertEqual(self.cli(root)[0], 0)
        self.assertEqual(self.builds()[-1], f"build --out-link {self.link(root)} nixpkgs#jdk25")
        self.assertTrue(os.readlink(self.link(root)).endswith("nixpkgs_jdk25"))
        self.assertEqual(self.manifest(root)["sdks"], {"jdk": "nixpkgs#jdk25"})

    def test_failed_build_exits_2_and_keeps_the_old_entry(self):
        root = self.project()
        self.config({"sdks": {"jdk": "nixpkgs#jdk21"}})
        self.cli(root)
        old_target = os.readlink(self.link(root))
        self.config({"sdks": {"jdk": "nixpkgs#jdk25", "py": "nixpkgs#python3"}})
        os.environ["STUB_NIX_FAIL"] = "1"
        code, _, err = self.cli(root)
        self.assertEqual(code, 2)
        self.assertIn("~/proj: nix build nixpkgs#jdk25 failed", err)
        self.assertEqual(os.readlink(self.link(root)), old_target)
        # The new SDK never built, so the manifest does not claim it.
        self.assertEqual(self.manifest(root)["sdks"], {"jdk": "nixpkgs#jdk21"})
        del os.environ["STUB_NIX_FAIL"]
        self.assertEqual(self.cli(root)[0], 0)
        self.assertEqual(self.manifest(root)["sdks"], {"jdk": "nixpkgs#jdk25", "py": "nixpkgs#python3"})

    def test_invalid_sdk_names_are_skipped(self):
        root = self.project()
        self.config({"sdks": {"../evil": "nixpkgs#hello", "a/b": "nixpkgs#hello", "..": "nixpkgs#hello"}})
        code, _, err = self.cli(root)
        self.assertEqual(code, 0)
        for name in ("'../evil'", "'a/b'", "'..'"):
            self.assertIn(f"invalid SDK name {name}", err)
        self.assertEqual(self.builds(), [])
        self.assertNotIn("sdks", self.manifest(root))

    def test_check_reports_a_pending_build_without_running_it(self):
        root = self.project()
        self.cli(root)
        self.config({"sdks": {"jdk": "nixpkgs#jdk21"}})
        code, out, _ = self.cli("--check", root)
        self.assertEqual(code, 1)
        self.assertIn("would update: nix build --out-link ~/proj/.nix/sdk/jdk nixpkgs#jdk21", out)
        self.assertEqual(self.builds(), [])
        self.assertFalse(os.path.lexists(self.link(root)))


if __name__ == "__main__":
    unittest.main()
