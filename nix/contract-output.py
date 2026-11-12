# SPDX-License-Identifier: MIT
"""Select owned contracts from actual Forge artifacts, retaining compiler proof."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def document(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def select(source, native, config_path, specs_path, destination, cast, solc_version):
    source, native, destination = map(Path, (source, native, destination))
    source = source.resolve()
    config = json.loads(Path(config_path).read_text())
    production = (source / config["src"]).resolve()
    dependencies = source / "dependencies"
    nonproduction = [(source / config.get(key, key)).resolve() for key in ["test", "script"]]
    if not production.is_relative_to(source) or production == source:
        raise ValueError("Forge production source root must be inside the project")
    specs = json.loads(Path(specs_path).read_text())
    artifacts = []
    for path in sorted(native.rglob("*.json")):
        artifact = json.loads(path.read_text())
        if not isinstance(artifact, dict) or "abi" not in artifact or "metadata" not in artifact:
            continue
        artifacts.append((path, artifact))
    for name, spec in specs.items():
        target = {spec["source"]: spec["contract"]}
        matches = [(path, artifact) for path, artifact in artifacts
                   if artifact["metadata"].get("settings", {}).get("compilationTarget") == target]
        if len(matches) != 1:
            raise ValueError("expected exactly one native compilation target: " + repr(target))
        path, artifact = matches[0]
        own_source = (source / spec["source"]).resolve()
        if not own_source.is_relative_to(production) or not own_source.is_file():
            raise ValueError("selected contract is not a production project source")
        metadata = json.loads(artifact["rawMetadata"])
        parsed = artifact["metadata"]
        # Forge normalizes remapping context prefixes and omits empty ABI fields
        # in its parsed view. Keep both views; compare their ownership identities.
        for key in ["compiler", "language", "sources"]:
            if metadata[key] != parsed[key]:
                raise ValueError("native metadata identity mismatch: " + key)
        if metadata["settings"]["compilationTarget"] != target:
            raise ValueError("raw native compilation target disagrees with Forge")
        if metadata["language"] != "Solidity" or metadata["compiler"]["version"].split("+")[0] != solc_version:
            raise ValueError("native Solidity compiler identity mismatch")
        public = destination / "contracts" / name
        proof = destination / "contract-proof" / name
        public.mkdir(parents=True)
        proof.mkdir(parents=True)
        sources = {}
        for relative, record in sorted(metadata["sources"].items()):
            native_source = (source / relative).resolve()
            if not native_source.is_relative_to(source) or not native_source.is_file():
                raise ValueError("compiler source escapes project: " + relative)
            if native_source.is_relative_to(dependencies):
                kind = "locked-dependency"
            elif any(native_source.is_relative_to(root) for root in nonproduction):
                raise ValueError("production contract imports a test/script source: " + relative)
            else:
                # Project-owned supporting sources may live outside Forge's src
                # root, e.g. a vendored interfaces directory in the same input.
                kind = "project"
            digest = subprocess.check_output([cast, "keccak"],
                input=("0x" + native_source.read_bytes().hex()).encode()).decode().strip()
            if digest != record["keccak256"]:
                raise ValueError("native compiler source hash mismatch: " + relative)
            stored = proof / "sources" / native_source.relative_to(source)
            stored.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(native_source, stored)
            sources[relative] = {"owner": kind, "sha256": sha(native_source), "keccak256": digest}
        if spec["source"] not in sources or sources[spec["source"]]["owner"] != "project":
            raise ValueError("compilation target has no project source ownership")
        # Preserve the original compiler artifact bytes and all native link/source metadata.
        shutil.copyfile(path, public / "contract.json")
        document(public / "abi.json", artifact["abi"])
        document(public / "bytecode.json", artifact["bytecode"])
        document(public / "deployed-bytecode.json", artifact["deployedBytecode"])
        exports = {"abi": artifact["abi"], "bytecode": artifact["bytecode"]["object"],
                   "deployedBytecode": artifact["deployedBytecode"]["object"],
                   "linkReferences": artifact["bytecode"]["linkReferences"],
                   "deployedLinkReferences": artifact["deployedBytecode"]["linkReferences"],
                   "contractName": spec["contract"], "sourceName": spec["source"],
                   "compilerVersion": metadata["compiler"]["version"]}
        (public / "main.mjs").write_text("".join("export const " + key + " = " + json.dumps(value) + ";\n"
                                               for key, value in exports.items()))
        (public / "main.d.ts").write_text("".join("export declare const " + key + ": " +
            ("readonly " if key == "abi" else "") + json.dumps(value) + ";\n" for key, value in exports.items()))
        document(proof / "model.json", {"source": spec["source"], "contract": spec["contract"],
            "artifact": str(path.relative_to(native)), "artifactSha256": sha(path),
            "rawMetadataSha256": hashlib.sha256(artifact["rawMetadata"].encode()).hexdigest(),
            "compiler": metadata["compiler"], "settings": metadata["settings"],
            "productionRoot": str(production.relative_to(source)),
            "sources": sources, "files": {p.name: sha(p) for p in sorted(public.iterdir())}})


if __name__ == "__main__":
    select(*sys.argv[1:])
