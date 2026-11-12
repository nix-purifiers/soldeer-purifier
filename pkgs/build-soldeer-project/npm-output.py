# SPDX-License-Identifier: MIT
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

artifact, spec_file, destination, npm = sys.argv[1:]
artifact, destination = Path(artifact), Path(destination)
spec = json.loads(Path(spec_file).read_text())
package = Path("npm-package")
package.mkdir()
files = sorted(p.name for p in artifact.iterdir())
metadata = {"name": spec["name"], "version": spec["version"], "type": "module",
            "exports": {".": {"types": "./main.d.ts", "default": "./main.mjs"}}, "files": files}
(package / "package.json").write_text(json.dumps(metadata, sort_keys=True) + "\n")
for name in files:
    shutil.copyfile(artifact / name, package / name)
archives = destination / "archives"
archives.mkdir(parents=True)
report = json.loads(subprocess.check_output([npm, "pack", "--offline", "--ignore-scripts", "--json",
                    "--pack-destination", str(archives)], cwd=package, text=True))
assert len(report) == 1
archive = archives / report[0]["filename"]
with tarfile.open(archive, "r:gz") as stream:
    assert {m.name for m in stream.getmembers() if m.isfile()} == {"package/"+name for name in files + ["package.json"]}
    assert json.loads(stream.extractfile("package/package.json").read()) == metadata
    for name in files:
        assert stream.extractfile("package/"+name).read() == (artifact/name).read_bytes()
graph = {"version": 1, "primaries": {metadata["name"]: "contract"}, "nodes": {"contract": {
    "name": metadata["name"], "version": metadata["version"], "package": metadata,
    "archive": archive.name, "contentHash": hashlib.sha256(archive.read_bytes()).hexdigest(), "dependencies": {}}}}
(destination/"graph.json").write_text(json.dumps(graph,sort_keys=True,indent=2)+"\n")
(destination/"pack.json").write_text(json.dumps(report,sort_keys=True,indent=2)+"\n")
