# Evaluates nix/home-module.nix against stub declarations of the few Home
# Manager options it sets, so the check needs no home-manager input. It
# compares the generated config JSON with the expected one and checks the
# activation script and the disabled cases.
{
  pkgs,
  self,
}:

let
  inherit (pkgs) lib;

  # The only part of Home Manager's lib the module uses.
  hmLib = lib.extend (
    _: _: {
      hm.dag.entryAfter = after: data: { inherit after data; };
    }
  );

  stubs =
    { lib, ... }:
    let
      inherit (lib) mkOption types;
    in
    {
      options = {
        home.packages = mkOption {
          type = types.listOf types.package;
          default = [ ];
        };
        home.activation = mkOption {
          type = types.attrsOf types.anything;
          default = { };
        };
        xdg.configFile = mkOption {
          type = types.attrsOf (types.submodule { options.source = mkOption { type = types.path; }; });
          default = { };
        };
        nix.package = mkOption {
          type = types.nullOr types.package;
          default = null;
        };
      };
    };

  evaluate =
    settings:
    (hmLib.evalModules {
      modules = [
        stubs
        (import ./home-module.nix self)
        { _module.args.pkgs = pkgs; }
        { programs.nix-jetbrains-project-setup = settings; }
      ];
    }).config;

  full = evaluate {
    enable = true;
    excludeFolders.target = true;
    excludePatterns."result-*" = false;
    sdks.jdk = "nixpkgs#jdk21";
    jvmOptions."-XX:+UseG1GC" = true;
    removeJvmOptions = [ "-XX:+UseConcMarkSweepGC" ];
    projects."~/a".excludeFolders.out = true;
    projects."~/b" = { };
  };

  expected = pkgs.writeText "expected.json" (
    builtins.toJSON {
      excludeFolders.target = true;
      excludePatterns."result-*" = false;
      sdks.jdk = "nixpkgs#jdk21";
      jvmOptions."-XX:+UseG1GC" = true;
      removeJvmOptions = [ "-XX:+UseConcMarkSweepGC" ];
      projects = {
        "~/a".excludeFolders.out = true;
        "~/b" = { };
      };
    }
  );

  # Empty settings are left out of the JSON, so the command's defaults apply.
  minimal = evaluate { enable = true; };
  noActivation = evaluate {
    enable = true;
    runOnActivation = false;
  };
  disabled = evaluate { excludeFolders.target = true; };

  configOf = c: c.xdg.configFile."nix-jetbrains-project-setup/config.json".source;
  activation = full.home.activation.nix-jetbrains-project-setup;
  package = self.packages.${pkgs.stdenv.hostPlatform.system}.default;

  checks = {
    "activation runs after linkGeneration" = activation.after == [ "linkGeneration" ];
    "package is installed" = full.home.packages == [ package ];
    "runOnActivation = false drops the activation" = noActivation.home.activation == { };
    "disabled module sets nothing" =
      disabled.home.packages == [ ] && disabled.xdg.configFile == { } && disabled.home.activation == { };
  };
  failed = lib.attrNames (lib.filterAttrs (_: ok: !ok) checks);
in
assert lib.assertMsg (
  failed == [ ]
) "home module checks failed: ${lib.concatStringsSep "; " failed}";
pkgs.runCommand "home-module-test"
  {
    nativeBuildInputs = [ pkgs.python3 ];
    activationScript = activation.data;
    passAsFile = [ "activationScript" ];
  }
  ''
    same() {
      python3 -c 'import json, sys; a, b = (json.load(open(p)) for p in sys.argv[1:]); sys.exit(a != b)' "$1" "$2" \
        || { echo "$1 differs from $2:"; cat "$1"; echo; cat "$2"; exit 1; }
    }
    same ${configOf full} ${expected}
    echo '{}' > empty.json
    same ${configOf minimal} empty.json
    # The activation applies --all with the generated config, and a failure only warns.
    grep -qF -- '${lib.getExe package} apply --all --config ${configOf full}' "$activationScriptPath"
    grep -qF -- '|| echo' "$activationScriptPath"
    touch $out
  ''
