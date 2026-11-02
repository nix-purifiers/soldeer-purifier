# SPDX-License-Identifier: MIT
{ pkgs, self }:
let
  python = pkgs.python3;
  fixture = ../examples/counter;
  project = pkgs.soldeer-purifier.buildSoldeerProject { src = fixture; };
  externalSource = builtins.path {
    path = fixture;
    name = "soldeer-external-source";
    filter =
      path: type:
      !(builtins.elem (baseNameOf path) [
        "soldeer.lock"
        "soldeer-purifier.lock.json"
        "dependencies"
        ".soldeer-purifier"
      ]);
  };
  external = pkgs.soldeer-purifier.buildSoldeerProject {
    src = externalSource;
    soldeerLock = fixture + "/soldeer.lock";
    lockFile = fixture + "/soldeer-purifier.lock.json";
  };
  errorCheck =
    case:
    pkgs.runCommand "soldeer-${case}"
      {
        nativeBuildInputs = [
          python
          pkgs.nix
        ];
        SOURCE = self;
        NIXPKGS_LIB = "${pkgs.path}/lib";
        PURIFIER = self.inputs.purifier;
        PYTHONPATH = self;
      }
      ''
        export HOME="$TMPDIR/home"
        mkdir -p "$HOME"
        python ${./eval-errors.py} ${case}
        touch "$out"
      '';
in
{
  environment = project.dependencies;
  package = project.packages.contracts;
  offline = project.tests;
  release = project.release;
  editor =
    pkgs.runCommand "soldeer-editor"
      {
        nativeBuildInputs = [
          pkgs.vscode-solidity-server
          python
        ];
      }
      ''
        export HOME="$TMPDIR/home"
        mkdir -p "$HOME"
        cp -r ${fixture} work
        chmod -R u+w work
        mkdir -p work/dependencies
        cp -rL ${project.dependencies}/. work/dependencies/
        cd work
        python ${./editor.py}
        touch "$out"
      '';
  unit = pkgs.runCommand "soldeer-unit" { nativeBuildInputs = [ python ]; } ''
    cp -r ${self} source
    chmod -R u+w source
    cd source
    python -m unittest discover -s tests -v
    touch "$out"
  '';
  conformance-external = pkgs.runCommand "soldeer-external-locks" { } ''
    test ! -e ${externalSource}/soldeer.lock
    test ! -e ${externalSource}/soldeer-purifier.lock.json
    cmp ${external.packages.contracts}/Counter.sol/Counter.json ${project.packages.contracts}/Counter.sol/Counter.json
    touch "$out"
  '';
}
// pkgs.lib.genAttrs [
  "conformance-stale"
  "conformance-tampered"
  "conformance-missing"
  "conformance-malformed"
] (name: errorCheck (pkgs.lib.removePrefix "conformance-" name))
