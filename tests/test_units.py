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
    def test_merged_merges_dicts_one_level_and_replaces_the_rest(self):
        a = {"d": {"x": True, "y": True}, "s": "old", "keep": 1}
        b = {"d": {"y": False, "z": True}, "s": "new"}
        self.assertEqual(njps.merged(a, b), {"d": {"x": True, "y": False, "z": True}, "s": "new", "keep": 1})
        self.assertEqual(a["d"], {"x": True, "y": True})  # inputs untouched

    def test_project_settings_layers_defaults_global_and_matching_project(self):
        root = os.path.join(self.home, "proj")
        cfg = {
            "excludeFolders": {"target": True},
            "jvmOptions": {"-Xmx1g": True},
            "projects": {
                "~/proj": {"excludeFolders": {".nix": False}, "sdks": {"jdk": "nixpkgs#jdk21"}},
                "~/other": {"excludePatterns": {"*.log": True}},
            },
        }
        self.assertEqual(
            njps.project_settings(cfg, root),
            {
                "excludeFolders": {".direnv": True, ".nix": False, "target": True},
                "excludePatterns": {"result": True, "result-*": True},
                "sdks": {"jdk": "nixpkgs#jdk21"},
            },
        )

    def test_project_settings_without_config_is_the_defaults(self):
        self.assertEqual(njps.project_settings({}, self.home), njps.DEFAULTS)

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
