# SPDX-License-Identifier: MIT
{
  lib,
  callPackage,
  runCommand,
  foundry,
  solc,
  gnutar,
  gzip,
  purifier,
}:
{
  src,
  lockFile ? src + "/soldeer-purifier.lock.json",
  soldeerLock ? src + "/soldeer.lock",
  fetchers ? { },
  srcFilter ?
    path: type:
    !(builtins.elem (baseNameOf path) [
      ".git"
      "dependencies"
      ".soldeer-purifier"
      "out"
      "cache"
      "broadcast"
      "result"
    ]),
  testCommand ? "forge test --offline --use ${solc}/bin/solc",
}:
let
  lock = purifier.checkLock (
    (import ./read-lock.nix { inherit lib; }) { inherit src lockFile soldeerLock; }
  );
  dependencies = callPackage ./dependencies.nix { inherit purifier; } { inherit lock fetchers; };
  source = lib.cleanSourceWith {
    inherit src;
    filter = srcFilter;
  };
  setup = ''
    export HOME="$TMPDIR/home"
    mkdir -p "$HOME" work
    cp -r ${source}/. work/
    chmod -R u+w work
    cp ${soldeerLock} work/soldeer.lock
    mkdir -p work/dependencies
    cp -rL ${dependencies}/. work/dependencies/
    cd work
  '';
  contracts =
    runCommand "soldeer-contracts"
      {
        nativeBuildInputs = [
          foundry
          solc
        ];
      }
      ''
        ${setup}
        forge build --offline --use ${solc}/bin/solc
        mkdir -p "$out"
        cp -r out/. "$out/"
      '';
  tests =
    runCommand "soldeer-tests"
      {
        nativeBuildInputs = [
          foundry
          solc
        ];
      }
      ''
        ${setup}
        ${testCommand}
        touch "$out"
      '';
  release =
    runCommand "soldeer-release"
      {
        nativeBuildInputs = [
          gnutar
          gzip
        ];
      }
      ''
        test -e ${tests}
        ${setup}
        cp ${lockFile} soldeer-purifier.lock.json
        mkdir -p "$out"
        tar --exclude=./dependencies --sort=name --mtime=@1 --owner=0 --group=0 --numeric-owner \
          -cf - . | gzip -n > "$out/source.tar.gz"
        tar --sort=name --mtime=@1 --owner=0 --group=0 --numeric-owner \
          -C ${contracts} -cf - . | gzip -n > "$out/contracts.tar.gz"
      '';
in
assert
  lock.forgeVersion == foundry.version
  || throw "soldeer-purifier: Forge toolchain changed; run soldeer-purifier lock";
assert
  lock.solcVersion == solc.version
  || throw "soldeer-purifier: compiler changed; run soldeer-purifier lock";
{
  packages.contracts = contracts;
  inherit tests release dependencies;
  fetches = lock.entries;
}
