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
  python3,
  nodejs,
  writeText,
}:
{
  src,
  lockFile ? src + "/soldeer-purifier.lock.json",
  soldeerLock ? src + "/soldeer.lock",
  fetchers ? { },
  contractTargets ? { },
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
    (import ../../lib-overlays/default/read-lock.nix { inherit lib; }) { inherit src lockFile soldeerLock; }
  );
  dependencies = callPackage ./dependencies.nix { inherit purifier; } { inherit lock fetchers; };
  source = lib.cleanSourceWith {
    inherit src;
    filter = srcFilter;
  };
  relative = path: builtins.isString path && path != "" && !(lib.hasPrefix "/" path)
    && !(lib.hasInfix "\\" path)
    && builtins.all (part: part != "" && part != "." && part != "..") (lib.splitString "/" path);
  coordinate = value: builtins.isString value && builtins.match "[A-Za-z0-9_][A-Za-z0-9_.-]*" value != null;
  version = value: builtins.isString value && builtins.match "[0-9]+\\.[0-9]+\\.[0-9]+(-[A-Za-z0-9.-]+)?" value != null;
  valid = target:
    builtins.isAttrs target
    && builtins.all (key: builtins.elem key [ "source" "contract" "webjar" "npm" "python" ]) (builtins.attrNames target)
    && relative (target.source or null)
    && builtins.isString (target.contract or null)
    && builtins.match "[A-Za-z_][A-Za-z0-9_]*" target.contract != null
    && ((target.webjar or null) == null || (
      builtins.isAttrs target.webjar
      && builtins.all (key: builtins.elem key [ "groupId" "artifactId" "version" ]) (builtins.attrNames target.webjar)
      && coordinate (target.webjar.groupId or "org.webjars.solidity")
      && coordinate (target.webjar.artifactId or null) && coordinate (target.webjar.version or null)
    ))
    && ((target.npm or null) == null || (
      builtins.isAttrs target.npm && builtins.attrNames target.npm == [ "name" "version" ]
      && builtins.isString (target.npm.name or null)
      && builtins.match "(@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*" target.npm.name != null
      && version (target.npm.version or null)
    ))
    && ((target.python or null) == null || (
      builtins.isAttrs target.python && builtins.attrNames target.python == [ "module" "name" "version" ]
      && coordinate (target.python.name or null) && version (target.python.version or null)
      && builtins.isString (target.python.module or null)
      && builtins.match "[a-z][a-z0-9_]*" target.python.module != null
    ));
  validTargets = builtins.isAttrs contractTargets
    && builtins.all (name: coordinate name && valid contractTargets.${name}) (builtins.attrNames contractTargets);
  specs = writeText "soldeer-contract-targets.json" (builtins.toJSON
    (lib.mapAttrs (_: target: { inherit (target) source contract; }) contractTargets));
  pythonBuilder = python3.withPackages (ps: [ ps.build ps.setuptools ps.wheel ]);
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
        outputs = [ "out" ] ++ lib.optional (contractTargets != { }) "proof";
        nativeBuildInputs = [
          foundry
          solc
        ] ++ lib.optional (contractTargets != { }) python3;
      }
      ''
        ${setup}
        forge build --offline --use ${solc}/bin/solc
        mkdir -p "$out"
        cp -r out/. "$out/"
        ${lib.optionalString (contractTargets != { }) ''
          forge config --json > "$TMPDIR/forge-config.json"
          python3 ${./contract-output.py} "$PWD" "$PWD/out" "$TMPDIR/forge-config.json" ${specs} "$proof" \
            ${foundry}/bin/cast ${lib.escapeShellArg lock.solcVersion}
        ''}
      '';
  artifacts = lib.mapAttrs (name: target:
    let
      artifact = runCommand "soldeer-contract-${name}" { outputs = [ "out" "proof" ]; } ''
        mkdir -p "$out" "$proof"
        cp -r ${contracts.proof}/contracts/${name}/. "$out/"
        cp -r ${contracts.proof}/contract-proof/${name}/. "$proof/"
      '';
      npmSpec = writeText "soldeer-npm-${name}.json" (builtins.toJSON target.npm);
      npmArchive = runCommand "soldeer-npm-${name}" { nativeBuildInputs = [ python3 nodejs ]; } ''
        export HOME="$TMPDIR/home" npm_config_cache="$TMPDIR/npm-cache"
        mkdir -p "$HOME"
        python3 ${./npm-output.py} ${artifact} ${npmSpec} "$out" ${nodejs}/bin/npm
      '';
      pythonSpec = writeText "soldeer-python-${name}.json" (builtins.toJSON target.python);
      pythonWheel = runCommand "soldeer-python-${name}" { nativeBuildInputs = [ pythonBuilder ]; } ''
        export HOME="$TMPDIR/home" SOURCE_DATE_EPOCH=315532800
        mkdir -p "$HOME"
        python3 ${./python-output.py} ${artifact} ${pythonSpec} "$out"
      '';
    in artifact
    // lib.optionalAttrs ((target.npm or null) != null) { inherit npmArchive; }
    // lib.optionalAttrs ((target.python or null) != null) { inherit pythonWheel; }
    // {
      projections = (purifier.resourceProjections {
        producer = artifact; roots."." = "."; inherit runCommand python3;
      }) // lib.optionalAttrs ((target.webjar or null) != null) (purifier.webjarProjections (
        { groupId = "org.webjars.solidity"; } // target.webjar // {
          producer = artifact; assets = artifact; inherit runCommand python3;
        }
      )) // lib.optionalAttrs ((target.npm or null) != null) (purifier.npmProjections {
        producer = artifact; graph = "${npmArchive}/graph.json"; archives = "${npmArchive}/archives";
        inherit runCommand python3;
      }) // lib.optionalAttrs ((target.python or null) != null) (purifier.pythonProjections {
        producer = artifact; repository = pythonWheel; inherit runCommand python3;
      });
    }
  ) contractTargets;
  projections = lib.mapAttrs (_: artifact: artifact.projections) artifacts;
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
assert lib.assertMsg validTargets
  "soldeer-purifier: contractTargets requires a relative production source, native contract name and optional WebJar/npm/Python coordinates";
{
  packages = { inherit contracts; }
    // lib.mapAttrs' (name: artifact: lib.nameValuePair "contract-${name}" artifact) artifacts;
  inherit artifacts projections;
  inherit tests release dependencies;
  fetches = lock.entries;
}
