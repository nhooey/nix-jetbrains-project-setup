---
title: Rider's .idea/.idea.<name>/ layout gets the same excludes
state: proposed
kind: end-state
touches: [src/nix_jetbrains_project_setup.py]
---

# Rider's `.idea/.idea.<name>/` layout gets the same excludes

A Rider project, whose settings live in `.idea/.idea.<name>/` with no
`modules.xml`, gets the same excluded folders and patterns as a project in
the `modules.xml` layout.

Today the excludes are skipped for a `.idea` without `modules.xml`; SDK
links are made either way.
