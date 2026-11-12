{ pkgs }:
let
  build = src: pkgs.soldeer-purifier.buildSoldeerProject {
    inherit src;
    contractTargets.counter = {
      source = "src/Counter.sol";
      contract = "Counter";
      webjar = { groupId = "org.webjars.solidity"; artifactId = "counter"; version = "1.0.0"; };
      npm = { name = "@fixture/counter-abi"; version = "1.0.0"; };
      python = { name = "fixture-counter-abi"; version = "1.0.0"; module = "counter_abi"; };
    };
  };
  record = src: value: let built = build src; in {
    inherit value;
    artifact = toString built.artifacts.counter;
    proof = toString built.artifacts.counter.proof;
    native = toString built.packages.contracts;
    unprojectedNative = toString (pkgs.soldeer-purifier.buildSoldeerProject { inherit src; }).packages.contracts;
    nativeTests = toString built.tests;
    web = toString built.projections.counter.web;
    maven = toString built.projections.counter.maven;
    npm = toString built.projections.counter.npm;
    npmCatalog = built.projections.counter.npm.catalog;
    python = toString built.projections.counter.python;
    pythonCatalog = built.projections.counter.python.catalog;
  };
  reject = target: !(builtins.tryEval (pkgs.soldeer-purifier.buildSoldeerProject {
    src = ./fixtures/contract42; contractTargets.counter = target;
  }).packages.contract-counter.drvPath).success;
  nodeModules = pkgs.importNpmLock.buildNodeModules {
    npmRoot = ./clients;
    inherit (pkgs) nodejs;
    derivationArgs.npmFlags = [ "--ignore-scripts" ];
  };
  python = pkgs.python3.withPackages (ps: [ ps.web3 ps.pip ps.packaging ]);
in
assert (pkgs.soldeer-purifier.buildSoldeerProject { src = ./fixtures/contract42; }).projections == { };
assert reject { source = "../Counter.sol"; contract = "Counter"; };
assert reject { source = "src/Counter.sol"; contract = "../Counter"; };
assert reject { source = "src/Counter.sol"; contract = "Counter"; python = { name = "example"; version = "1.0.0"; module = "../example"; }; };
pkgs.runCommand "soldeer-contract-consumers" {
  nativeBuildInputs = [ python pkgs.nodejs pkgs.foundry pkgs.jdk pkgs.gradle pkgs.typescript ];
  spec = builtins.toJSON {
    versions = [ (record ./fixtures/contract42 42) (record ./fixtures/contract43 43) ];
    nodeModules = toString nodeModules;
    node = "${pkgs.nodejs}/bin/node";
    npm = "${pkgs.nodejs}/bin/npm";
    anvil = "${pkgs.foundry}/bin/anvil";
    typescript = "${pkgs.typescript}/bin/tsc";
  };
  passAsFile = [ "spec" ];
} ''
  export HOME="$TMPDIR/home" GRADLE_USER_HOME="$TMPDIR/gradle-home"
  mkdir -p "$HOME"
  python3 ${./contracts}/proof.py "$specPath" "$out"
''
