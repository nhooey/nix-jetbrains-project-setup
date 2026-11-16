---
title: The project SDK is set in .idea/misc.xml
state: proposed
kind: end-state
needs: [sdks-in-jdk-table]
touches: [src/nix_jetbrains_project_setup.py]
---

# The project SDK is set in `.idea/misc.xml`

A project's SDK is set in its `.idea/misc.xml` to one of the SDKs registered
in `jdk.table.xml`, so opening the project needs no SDK picked by hand.

Today the command doesn't read or write `.idea/misc.xml`.
