{
  lib,
  stdenvNoCC,
  python3,
  git,
  makeWrapper,
}:

stdenvNoCC.mkDerivation {
  pname = "nix-jetbrains-project-setup";
  version = "0.1.0";

  src = lib.fileset.toSource {
    root = ./.;
    fileset = lib.fileset.unions [
      ./src
      ./tests
    ];
  };

  nativeBuildInputs = [ makeWrapper ];
  buildInputs = [ python3 ];
  nativeCheckInputs = [
    python3
    git
  ];

  dontConfigure = true;
  dontBuild = true;

  doCheck = true;
  checkPhase = ''
    runHook preCheck
    export HOME=$TMPDIR/home
    mkdir -p "$HOME"
    python3 -m unittest discover -s tests -v
    runHook postCheck
  '';

  # `nix` is deliberately not wrapped in: SDK links are built with the
  # caller's own nix, the one that talks to their daemon. git goes at the
  # end of PATH, only as a fallback for the tracked/ignored checks.
  installPhase = ''
    runHook preInstall
    install -D -m u=rwx,go=rx src/nix_jetbrains_project_setup.py $out/bin/nix-jetbrains-project-setup
    wrapProgram $out/bin/nix-jetbrains-project-setup --suffix PATH : ${lib.makeBinPath [ git ]}
    runHook postInstall
  '';

  meta = {
    description = "Set up JetBrains IDEs for Nix projects without touching version control";
    homepage = "https://github.com/nhooey/nix-jetbrains-project-setup";
    license = lib.licenses.mit;
    mainProgram = "nix-jetbrains-project-setup";
    platforms = lib.platforms.unix;
  };
}
