# SPDX-License-Identifier: MIT
{
  project,
  lockFile,
  soldeerLock,
  target,
}:
let
  pkgs = import (builtins.toPath "@nixpkgs@") { };
  purifier = import (builtins.toPath "@purifier@/nix/lib") { inherit (pkgs) lib; };
  result = pkgs.callPackage ../pkgs/build-soldeer-project/default.nix { inherit purifier; } {
    src = /. + project;
    lockFile = /. + lockFile;
    soldeerLock = /. + soldeerLock;
  };
in
if target == "dependencies" then
  result.dependencies
else if target == "runtime" then
  pkgs.runCommand "soldeer-runtime" { } ''ln -s @runtime@ "$out"''
else if target == "release" then
  result.release
else
  throw "soldeer-purifier: invalid target"
