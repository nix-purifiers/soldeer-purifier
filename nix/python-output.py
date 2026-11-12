# SPDX-License-Identifier: MIT
"""Build an ordinary wheel containing native contract data and Python accessors."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

artifact, spec_file, destination = map(Path, sys.argv[1:])
spec = json.loads(spec_file.read_text())
source = Path("python-package")
module = source / spec["module"]
module.mkdir(parents=True)
for name in ["contract.json", "abi.json", "bytecode.json", "deployed-bytecode.json"]:
    shutil.copyfile(artifact/name,module/name)
(module/"__init__.py").write_text('''import json
from importlib.resources import files

contract = json.loads(files(__package__).joinpath("contract.json").read_text())
abi = contract["abi"]
bytecode = contract["bytecode"]["object"]
deployed_bytecode = contract["deployedBytecode"]["object"]
link_references = contract["bytecode"]["linkReferences"]
deployed_link_references = contract["deployedBytecode"]["linkReferences"]
''')
(source/"pyproject.toml").write_text('''[build-system]
requires = ["setuptools", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = '''+json.dumps(spec["name"])+'''
version = '''+json.dumps(spec["version"])+'''
requires-python = ">=3.9"

[tool.setuptools]
packages = ['''+json.dumps(spec["module"])+''']

[tool.setuptools.package-data]
"*" = ["*.json"]
''')
destination.mkdir(parents=True)
subprocess.run([sys.executable,"-m","build","--wheel","--no-isolation","--outdir",str(destination)],cwd=source,check=True)
wheels=list(destination.glob("*.whl"))
assert len(wheels)==1
with zipfile.ZipFile(wheels[0]) as wheel:
    for name in ["contract.json","abi.json","bytecode.json","deployed-bytecode.json"]:
        assert wheel.read(spec["module"]+"/"+name)==(artifact/name).read_bytes()
