---
title: Each SDK is registered in the IDE-wide jdk.table.xml
state: proposed
kind: end-state
touches: [src/nix_jetbrains_project_setup.py]
---

# Each SDK is registered in the IDE-wide `jdk.table.xml`

Each SDK in `sdks` is registered once in each IDE's `jdk.table.xml`, under a
stable name pointing at `.nix/sdk/<name>`, so the IDE lists it without the
user adding it by hand.

The file is written only while that IDE isn't running: an open IDE rewrites
`jdk.table.xml` on exit and would drop the entry.

Today the command links `.nix/sdk/<name>` in each project and doesn't touch
`jdk.table.xml`.
