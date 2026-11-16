"""Unit tests for the pure functions: reconcile(), the config merge and the
small helpers. These take values and return values, so they need no files
beyond the temp dir vmoptions_name() lists."""

import os
import unittest

from support import Base, njps

SRC = "proj.iml"


def reconcile(desired, owned=(), present=(), optouts=None, block=False):
    return njps.reconcile(desired, list(owned), list(present), optouts or {}, SRC, block=block)


def optout(value):
    return {"value": value, "was": not value, "source": SRC}


class ReconcileTests(unittest.TestCase):
    def test_fresh_file_gets_every_enabled_key(self):
        add, remove, owned, kept = reconcile({"a": True, "b": False, "c": True})
        self.assertEqual((add, remove, owned, kept), (["a", "c"], [], ["a", "c"], {}))

    def test_settled_state_is_a_fixed_point(self):
        for block in (False, True):
            with self.subTest(block=block):
                result = reconcile({"a": True}, owned=["a"], present=["a"], block=block)
                self.assertEqual(result, ([], [], ["a"], {}))

    def test_key_turned_off_in_config_is_removed_and_disowned(self):
        add, remove, owned, kept = reconcile({"a": False, "b": True}, owned=["a", "b"], present=["a", "b"])
        self.assertEqual((add, remove, owned, kept), ([], ["a"], ["b"], {}))

    def test_key_dropped_from_config_counts_as_off(self):
        self.assertEqual(reconcile({}, owned=["a"], present=["a"]), ([], ["a"], [], {}))

    def test_owned_key_deleted_in_gui_becomes_opt_out_not_restored(self):
        add, remove, owned, kept = reconcile({"a": True}, owned=["a"], present=[])
        self.assertEqual((add, remove, owned, kept), ([], [], [], {"a": optout(False)}))

    def test_opt_out_lasts_while_file_and_config_still_disagree(self):
        result = reconcile({"a": True}, owned=[], present=[], optouts={"a": optout(False)})
        self.assertEqual(result, ([], [], [], {"a": optout(False)}))

    def test_opt_out_clears_once_config_agrees(self):
        self.assertEqual(reconcile({"a": False}, optouts={"a": optout(False)}), ([], [], [], {}))

    def test_opt_out_clears_when_gui_restores_the_key_without_adopting_it(self):
        # The user put it back by hand: it is theirs now, not the tool's.
        result = reconcile({"a": True}, present=["a"], optouts={"a": optout(False)})
        self.assertEqual(result, ([], [], [], {}))

    def test_unowned_keys_outside_a_block_are_the_users(self):
        # A user's own entry is neither removed when off nor adopted when on.
        self.assertEqual(reconcile({"a": False, "b": True}, present=["a", "b"]), ([], [], [], {}))

    def test_unowned_key_inside_the_block_was_added_in_the_gui(self):
        add, remove, owned, kept = reconcile({"a": True}, owned=["a"], present=["a", "x"], block=True)
        self.assertEqual((add, remove, owned, kept), ([], [], ["a"], {"x": optout(True)}))

    def test_unowned_key_inside_the_block_that_config_wants_is_adopted(self):
        self.assertEqual(reconcile({"a": True}, present=["a"], block=True), ([], [], ["a"], {}))

    def test_existing_opt_out_record_is_kept_verbatim(self):
        rec = {"value": True, "was": False, "source": "old.vmoptions"}
        result = njps.reconcile({}, [], ["x"], {"x": rec}, "idea.vmoptions", block=True)
        self.assertIs(result[3]["x"], rec)


class ConfigTests(Base):
    def test_merged_merges_dicts_at_every_level_and_replaces_the_rest(self):
        a = {"d": {"x": True, "y": True, "n": {"p": 1, "q": 2}}, "s": "old", "l": [1, 2], "keep": 1}
        b = {"d": {"y": False, "z": True, "n": {"q": 3}}, "s": "new", "l": [3]}
        self.assertEqual(
            njps.merged(a, b),
            {"d": {"x": True, "y": False, "z": True, "n": {"p": 1, "q": 3}}, "s": "new", "l": [3], "keep": 1},
        )
        self.assertEqual(a["d"], {"x": True, "y": True, "n": {"p": 1, "q": 2}})  # inputs untouched

    def test_project_settings_layers_defaults_global_and_matching_project(self):
        root = os.path.join(self.home, "proj")
        self.config(
            {
                "excludeFolders": {"target": True},
                "jvmOptions": {"-Xmx1g": True},
                "projects": {
                    "~/proj": {"excludeFolders": {".nix": False}, "sdks": {"jdk": "nixpkgs#jdk21"}},
                    "~/other": {"excludePatterns": {"*.log": True}},
                },
            }
        )
        self.assertEqual(
            njps.project_settings(njps.load_config(None), root),
            {
                "excludeFolders": {".direnv": True, ".nix": False, "target": True},
                "excludePatterns": {"result": True, "result-*": True},
                "sdks": {"jdk": "nixpkgs#jdk21"},
            },
        )

    def test_tilde_shortens_only_paths_under_home(self):
        self.assertEqual(njps.tilde(self.home), "~")
        self.assertEqual(njps.tilde(os.path.join(self.home, "p")), "~/p")
        self.assertEqual(njps.tilde(self.home + "x/p"), self.home + "x/p")
        self.assertEqual(njps.tilde("/elsewhere"), "/elsewhere")

    def test_nix_attr(self):
        self.assertEqual(njps.nix_attr("result"), "result")
        self.assertEqual(njps.nix_attr("result-*"), '"result-*"')
        self.assertEqual(njps.nix_attr(".nix"), '".nix"')
        self.assertEqual(njps.nix_attr("-Xmx4096m"), '"-Xmx4096m"')


class ShippedDefaultsTests(Base):
    def test_defaults_file_holds_every_key_with_its_default(self):
        self.assertEqual(
            njps.load_defaults(),
            {
                "excludeFolders": {".direnv": True, ".nix": True},
                "excludePatterns": {"result": True, "result-*": True},
                "sdks": {},
                "jvmOptions": {},
                "removeJvmOptions": [],
                "projects": {},
            },
        )
        self.assertLessEqual(set(njps.PROJECT_KEYS), set(njps.load_defaults()))

    def test_empty_or_missing_user_config_gives_exactly_the_defaults(self):
        self.assertEqual(njps.load_config(None), njps.load_defaults())  # Base writes {}
        os.remove(os.path.join(self.home, ".config", njps.NAME, "config.json"))
        self.assertEqual(njps.load_config(None), njps.load_defaults())

    def test_sparse_user_config_changes_only_its_keys(self):
        self.config({"excludeFolders": {".nix": False}, "removeJvmOptions": ["-server"]})
        want = njps.load_defaults()
        want["excludeFolders"][".nix"] = False
        want["removeJvmOptions"] = ["-server"]
        self.assertEqual(njps.load_config(None), want)

    def assertRefused(self, cfg, message):
        self.config(cfg)
        with self.assertRaises(njps.ConfigError) as raised:
            njps.load_config(None)
        self.assertIn(message, str(raised.exception))

    def test_unknown_key_is_refused_with_the_closest_known_one(self):
        self.assertRefused({"excludeFolder": {}}, "unknown key 'excludeFolder' (did you mean 'excludeFolders'?)")

    def test_unknown_or_global_only_key_in_a_project_is_refused(self):
        self.assertRefused({"projects": {"~/p": {"jvmOptions": {}}}}, "projects.\"~/p\": unknown key 'jvmOptions'")
        self.assertRefused({"projects": {"~/p": []}}, 'projects."~/p": expected an object')

    def test_value_of_the_wrong_kind_is_refused(self):
        self.assertRefused([], "expected an object")
        self.assertRefused({"removeJvmOptions": "-server"}, "removeJvmOptions must be list, not str")
        self.assertRefused({"projects": {"~/p": {"sdks": []}}}, "sdks must be dict, not list")

    def test_entry_of_the_wrong_kind_is_refused(self):
        # A string is truthy, so "no" would otherwise exclude the folder.
        self.assertRefused({"excludeFolders": {"x": "no"}}, 'excludeFolders."x" must be bool, not str')
        self.assertRefused({"jvmOptions": {"-Xmx1g": 1}}, 'jvmOptions."-Xmx1g" must be bool, not int')
        self.assertRefused({"removeJvmOptions": ["-server", 1]}, "removeJvmOptions[1] must be str, not int")
        # An int installable would otherwise crash the nix build call.
        self.assertRefused(
            {"projects": {"~/p": {"sdks": {"jdk": 21}}}}, 'projects."~/p": sdks."jdk" must be str, not int'
        )

    def test_cli_reports_a_refused_config_and_changes_nothing(self):
        root = self.project()
        before = self.snapshot(root)
        self.config({"exclude": {}})
        code, _, err = self.cli(root)
        self.assertEqual(code, 2)
        self.assertIn(f"{njps.NAME}: error: ~/.config/{njps.NAME}/config.json: unknown key 'exclude'", err)
        self.assertEqual(self.snapshot(root), before)


class VmoptionsNameTests(Base):
    def names(self, *files, product="idea"):
        ide_dir = os.path.join(self.tmp, "ide")
        os.makedirs(ide_dir, exist_ok=True)
        for f in files:
            open(os.path.join(ide_dir, f), "w").close()
        return njps.vmoptions_name(ide_dir, product)

    def test_product_file_wins_over_the_64_bit_one(self):
        self.assertEqual(self.names("idea64.vmoptions", "idea.vmoptions"), "idea.vmoptions")

    def test_64_bit_file_when_alone(self):
        self.assertEqual(self.names("idea64.vmoptions", "custom.vmoptions"), "idea64.vmoptions")

    def test_any_vmoptions_file_for_an_unknown_product(self):
        self.assertEqual(self.names("b.vmoptions", "a.vmoptions", "x.txt", product=None), "a.vmoptions")

    def test_empty_dir_names_the_product_file_or_nothing(self):
        self.assertEqual(self.names(), "idea.vmoptions")
        self.assertIsNone(self.names(product=None))


if __name__ == "__main__":
    unittest.main()
