#!/usr/bin/env bash
set -euo pipefail
system="$(nix eval --impure --raw --expr builtins.currentSystem)"
nix build ".#checks.${system}.package" --no-link
nix build ".#checks.${system}.package" --no-link --rebuild
nix build ".#checks.${system}.release" --no-link
nix build ".#checks.${system}.release" --no-link --rebuild
nix build ".#checks.${system}.contracts" --no-link --rebuild
