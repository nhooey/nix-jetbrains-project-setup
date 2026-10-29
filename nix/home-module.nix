# Home Manager module: writes the config JSON and, by default, applies it
# during activation. It never links IDE files from the store; the command
# merges into them.
self:
{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.programs.nix-jetbrains-project-setup;
  inherit (lib) mkOption types;

  onOff =
    description:
    mkOption {
      type = types.attrsOf types.bool;
      default = { };
      inherit description;
    };

  sdksOption = mkOption {
    type = types.attrsOf types.str;
    default = { };
    example = {
      jdk = "nixpkgs#jdk21";
    };
    description = "SDK name to Nix installable, built to `<project>/.nix/sdk/<name>`.";
  };

  projectOptions = {
    excludeFolders = onOff "Excluded folders for this project, merged onto the global ones.";
    excludePatterns = onOff "Exclude patterns for this project, merged onto the global ones.";
    sdks = sdksOption;
  };

  nonEmpty = lib.filterAttrs (_: v: v != { } && v != [ ]);

  settings = nonEmpty {
    inherit (cfg)
      excludeFolders
      excludePatterns
      sdks
      jvmOptions
      removeJvmOptions
      ;
    projects = lib.mapAttrs (_: nonEmpty) cfg.projects;
  };

  configFile = (pkgs.formats.json { }).generate "nix-jetbrains-project-setup.json" settings;

  nixPackage = if config.nix.package != null then config.nix.package else pkgs.nix;
in
{
  options.programs.nix-jetbrains-project-setup = {
    enable = lib.mkEnableOption "nix-jetbrains-project-setup";

    package = mkOption {
      type = types.package;
      default = self.packages.${pkgs.stdenv.hostPlatform.system}.default;
      defaultText = lib.literalExpression "nix-jetbrains-project-setup.packages.\${system}.default";
      description = "The nix-jetbrains-project-setup package.";
    };

    excludeFolders = onOff ''
      Folders to exclude, relative to the content root. Merged onto the
      built-in defaults (`.direnv`, `.nix`); set one to `false` to drop it.
    '';
    excludePatterns = onOff ''
      Exclude patterns. Merged onto the built-in defaults (`result`,
      `result-*`); set one to `false` to drop it.
    '';
    sdks = sdksOption;

    jvmOptions = onOff "JVM option lines kept in the managed block of every installed IDE's vmoptions file.";

    removeJvmOptions = mkOption {
      type = types.listOf types.str;
      default = [ ];
      example = [
        "-XX:+UseConcMarkSweepGC"
        "-XX:CMSInitiatingOccupancyFraction=*"
      ];
      description = "Lines outside the managed block to delete (shell-style globs).";
    };

    projects = mkOption {
      type = types.attrsOf (types.submodule { options = projectOptions; });
      default = { };
      example = {
        "~/git/nhooey/eventura".excludeFolders.target = true;
      };
      description = "Per-project settings, keyed by path (`~` allowed).";
    };

    runOnActivation = mkOption {
      type = types.bool;
      default = true;
      description = ''
        Run `nix-jetbrains-project-setup apply --all` during activation for
        every listed project and the JVM options. Failures only warn.
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = [ cfg.package ];

    xdg.configFile."nix-jetbrains-project-setup/config.json".source = configFile;

    home.activation.nix-jetbrains-project-setup = lib.mkIf cfg.runOnActivation (
      lib.hm.dag.entryAfter [ "linkGeneration" ] ''
        PATH="$PATH:${lib.makeBinPath [ nixPackage ]}" \
          run ${lib.getExe cfg.package} apply --all --config ${configFile} \
          || echo "nix-jetbrains-project-setup: apply failed; continuing" >&2
      ''
    );
  };
}
