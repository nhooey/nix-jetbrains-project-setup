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

      imports = [ inputs.treefmt-nix.flakeModule ];

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

          devShells.default = pkgs.mkShell {
            packages = [
              pkgs.python3
              pkgs.git
              pkgs.ruff
            ];
          };
        };
    };
}
