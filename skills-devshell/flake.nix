{
  description = "nix-jetbrains-project-setup dev-shell skill set: an isolated sub-flake the root dev shell runs at runtime, never a root input, so the skill sources live only in this flake's lock.";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    systems.url = "github:nix-systems/default";

    # The builder lib; it carries no skill inputs.
    agent-skill-flake = {
      url = "github:nhooey/agent-skill-flake";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    # Skill sources. They follow `nixpkgs` but not `agent-skill-flake`, so
    # each keeps its own compatible builder.

    # skillspkgs' per-family combinations; this repository is in the Nix
    # tooling family.
    skillspkgs-combinations = {
      url = "github:nhooey/skillspkgs?dir=sources/combinations";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    python-skills = {
      url = "github:nhooey/python-skills";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    {
      nixpkgs,
      agent-skill-flake,
      ...
    }@inputs:
    agent-skill-flake.lib.mkDevshellSkillsFlake {
      inherit nixpkgs;
      systems = import inputs.systems;
      name = "nix-jetbrains-project-setup-devshell";
      sources = [
        # The Nix tooling family's skills: the shared base, input bumping,
        # shipped defaults and changelogs.
        { source = inputs.skillspkgs-combinations.combinations.nix-tooling; }
        # The command itself is Python 3, standard library only, which the
        # rest of the Nix tooling family doesn't share.
        {
          source = inputs.python-skills;
          skills = [ "python-hygiene-functional-style" ];
        }
      ];
    };
}
