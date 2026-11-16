"""End-to-end tests for the managed block in each IDE's vmoptions file."""

import json
import os
import unittest

from support import VMOPTIONS, Base, njps


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



if __name__ == "__main__":
    unittest.main()
