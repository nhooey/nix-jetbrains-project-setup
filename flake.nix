{
  description = "Set up JetBrains IDEs for Nix projects without touching version control";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    flake-parts = {
      url = "github:hercules-ci/flake-parts";
      inputs.nixpkgs-lib.follows = "nixpkgs";
    };

    systems.url = "github:nix-systems/default";

    treefmt-nix = {
      url = "github:numtide/treefmt-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    # The `flakeModules.devshellSkills` module for the dev shell. The dev
    # shell's skills live in the `skills-devshell/` sub-flake, run at
    # runtime, so this flake carries no skill inputs.
    agent-skill-flake = {
      url = "github:nhooey/agent-skill-flake";
      inputs = {
        nixpkgs.follows = "nixpkgs";
        treefmt-nix.follows = "treefmt-nix";
      };
    };
  };

  outputs =
    inputs@{
      self,
      flake-parts,
      systems,
      ...
    }:
    flake-parts.lib.mkFlake { inherit inputs; } {
      systems = import systems;

      imports = [
        inputs.agent-skill-flake.flakeModules.devshellSkills
        inputs.treefmt-nix.flakeModule
      ];

      agent-skill-flake.devshellSkills.name = "nix-jetbrains-project-setup";

      flake.homeModules.default = import ./nix/home-module.nix self;

      perSystem =
        { pkgs, config, ... }:
        {
          packages.default = pkgs.callPackage ./package.nix { };

          checks = {
            # The unittest suite runs in the package's checkPhase.
            package = config.packages.default;
          };

          treefmt = {
            projectRootFile = "flake.nix";
            programs = {
              nixfmt.enable = true;
              ruff-format.enable = true;
            };
            settings.formatter.ruff-format.options = [ "--line-length=120" ];
          };

          devshells.default = {
            # The motd keeps the project's name, but the launcher must not
            # shadow the installed `nix-jetbrains-project-setup` command.
            name = "nix-jetbrains-project-setup-devshell";
            packages = [
              pkgs.python3
              pkgs.git
              pkgs.ruff
            ];
          };
        };
    };
}
