# soldeer-purifier

Locked, Nix-resolved Solidity dependencies for Soldeer and Forge.

## Quickstart

In your existing Foundry project:

```sh
nix shell 'github:nix-purifiers/soldeer-purifier'
soldeer-purifier lock
soldeer-purifier prefetch
forge build
forge test
```

Commit `soldeer.lock`, `soldeer-purifier.lock.json` and the native remappings.
Versions, URLs and archive checksums stay in Soldeer's lock. The companion
adds configuration fingerprints, Git NAR hashes and extraction metadata.
Forge runs in your working tree using Nix-resolved dependencies and compiler.

This integration requires the supplied Forge wrapper. You can install it
through your normal Nix configuration. Without a purifier lock it warns and
runs ordinary, impure Forge. Invalid or stale locks fail with a repair command.

## Development loop

Edit dependencies in `foundry.toml` or `soldeer.toml`, then:

```sh
soldeer-purifier lock
soldeer-purifier prefetch
forge build
forge test
```

`lock` retains native selections, including pinned Git revisions when a
branch moves. Unchanged locks are byte-for-byte stable. To change selections:

```sh
soldeer-purifier update
soldeer-purifier prefetch
```

Soldeer has no targeted update operation; named updates are not supported.
Dependency changes go through the purifier CLI. Ordinary source edits do not
require relocking; configuration and remapping edits do.

## Working offline

Prefetch roots the dependencies, Forge, Solidity compiler and editor worker.
The Forge wrapper builds and tests with `--offline` and the locked compiler.
The native project cache is materialized from immutable Nix store sources.
The wrapper checks materialized files against their recorded content before
builds and rejects changed dependencies. Existing entries
are retained with `.before-purifier` suffixes when first replaced.

```sh
soldeer-purifier prefetch
forge build
forge test
```

## Editor

Run `vscode-solidity-server --stdio` from the same shell. The project keeps
its native remappings, and dependency sources are available in `dependencies`.
The language-server check resolves a definition into locked forge-std sources.

## Troubleshooting

- **Configuration or lock changed:** run `soldeer-purifier lock`, then `prefetch`.
- **Wrong compiler:** this scope delivers Solidity 0.8.33 and Forge 1.8.4.
  Override the scope's `solc`/`foundry` and relock for another toolchain.
- **Existing cache backup:** move the extra entry aside before prefetching;
  previous backups are preserved.
- **Missing metadata:** `lock` repairs the companion from the native resolution.

External locks leave the working tree's native lock unchanged:

```sh
soldeer-purifier \
  --soldeer-lock ../locks/soldeer.lock \
  --lockfile ../locks/soldeer.json lock
soldeer-purifier \
  --soldeer-lock ../locks/soldeer.lock \
  --lockfile ../locks/soldeer.json prefetch
```

Set `SOLDEER_PURIFIER_SOLDEER_LOCK` and `SOLDEER_PURIFIER_LOCKFILE` to the same
paths for the Forge wrapper. A missing external native lock starts from the
working copy's lock.

## Supported language repositories

Public Soldeer registry packages, public ZIP URLs and Git dependencies are
supported. Git sources use the native locked revision and a NAR hash.
Recursive Soldeer dependencies, private packages without stable URLs and
names requiring platform-dependent filename sanitization are not supported.
Use one of `foundry.toml` or `soldeer.toml`. Native lock format 2 requires
Soldeer 0.12, supplied by Forge 1.8.4. The flake targets x86_64 and ARM Linux.

No native plugin repository is needed. GitHub Pages hosts the documentation.

## Examples

`examples/counter` imports forge-std and runs a real Solidity test:

```sh
nix shell 'github:nix-purifiers/soldeer-purifier'
cd examples/counter
soldeer-purifier prefetch
forge test
```

### Optional Nix build

The overlay adds only the `soldeer-purifier` scope:

```nix
let
  pkgs = import nixpkgs {
    inherit system;
    overlays = [ purifier.overlays.default ];
  };
  project = pkgs.soldeer-purifier.buildSoldeerProject {
    src = ./.;
    soldeerLock = ../locks/soldeer.lock;
    lockFile = ../locks/soldeer.json;
  };
in {
  packages.default = project.packages.contracts;
  checks.default = project.tests;
}
```

The result exposes `packages.contracts`, `tests`, `release` and `fetches`.
The builder supports `fetchers`, `srcFilter`, `testCommand` and scope overrides.
`release` contains deterministic source and compiled contract archives:

```sh
soldeer-purifier publish \
  --repo OWNER/PROJECT --tag v1.0.0
```

`lib.soldeer-purifier.readLock` reads the native TOML and companion JSON during
Nix evaluation, without import-from-derivation.

## Credits

The purifier idea was inspired by nixcloud's
[cargo (libnix)](https://github.com/nixcloud/cargo).
