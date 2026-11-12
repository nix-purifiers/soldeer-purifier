#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Native compilation/selection rejects nonproduction and stale contract artifacts."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

repo = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='soldeer-negative-') as temporary:
    temporary = Path(temporary)
    for name, source, contract, expected in [
        ('missing-contract', 'src/Counter.sol', 'Missing', 'expected exactly one native compilation target'),
        ('test-contract', 'test/Counter.t.sol', 'CounterTest', 'not a production project source'),
        ('dependency-contract', 'dependencies/forge-std-1.11.0/src/StdMath.sol', 'stdMath', 'not a production project source'),
        ('test-import', 'src/Counter.sol', 'Counter', 'production contract imports a test/script source'),
    ]:
        selected_source = 'f.outPath+"/tests/fixtures/contract42"'
        if name == 'test-import':
            imported = temporary / 'test-import'
            shutil.copytree(repo / 'tests/fixtures/contract42', imported)
            (imported / 'src/Counter.sol').write_text('''// SPDX-License-Identifier: MIT
pragma solidity ^0.8.33;
import {TestHelper} from "../test/ProductionProbe.sol";
contract Counter { function value() external pure returns (uint256) { return TestHelper.answer(); } }
''')
            (imported / 'test/ProductionProbe.sol').write_text('''// SPDX-License-Identifier: MIT
pragma solidity ^0.8.33;
library TestHelper { function answer() internal pure returns (uint256) { return 42; } }
''')
            (imported / 'test/Counter.t.sol').write_text('// SPDX-License-Identifier: MIT\npragma solidity ^0.8.33;\ncontract BuildProbe {}\n')
            selected_source = 'builtins.path {path=builtins.toPath '+json.dumps(str(imported))+';name="test-import-source";}'
        expression = f'''let f=builtins.getFlake {json.dumps('git+file://'+str(repo))};
          p=import f.inputs.nixpkgs {{system=builtins.currentSystem;overlays=[f.overlays.default];}};
          in (p.soldeer-purifier.buildSoldeerProject {{src={selected_source};
            contractTargets.bad={{source={json.dumps(source)};contract={json.dumps(contract)};}};
          }}).artifacts.bad'''
        result = subprocess.run(['nix', 'build', '--impure', '--no-link', '-L', '--expr', expression],
            capture_output=True, text=True, timeout=180)
        assert result.returncode != 0 and expected in result.stderr, (name, result.stdout, result.stderr)
        print(json.dumps({'case': name, 'exitCode': result.returncode, 'expectedDiagnostic': expected}), flush=True)
    expression = f'''let f=builtins.getFlake {json.dumps('git+file://'+str(repo))};
      p=import f.inputs.nixpkgs {{system=builtins.currentSystem;overlays=[f.overlays.default];}};
      in {{cast="${{p.foundry}}/bin/cast";version=p.solc.version;
        baseline=(p.soldeer-purifier.buildSoldeerProject {{src=f.outPath+"/examples/counter";}}).packages.contracts.drvPath;}}'''
    native = json.loads(subprocess.check_output(['nix', 'eval', '--impure', '--json', '--expr', expression], text=True))
    baseline = Path(subprocess.check_output(['nix', 'build', '--no-link', '--print-out-paths', native['baseline']+'^out'], text=True).strip())
    source = temporary / 'source'
    shutil.copytree(repo / 'examples/counter', source, ignore=shutil.ignore_patterns('out', 'cache', 'dependencies', '.soldeer-purifier'))
    path = source / 'src/Counter.sol'
    path.write_text(path.read_text().replace('value++', 'value += 2'))
    config = temporary / 'config.json'
    config.write_text(subprocess.check_output([str(Path(native['cast']).with_name('forge')), 'config', '--json'], cwd=source, text=True))
    specs = temporary / 'targets.json'
    specs.write_text(json.dumps({'bad': {'source': 'src/Counter.sol', 'contract': 'Counter'}}))
    result = subprocess.run(['python3', str(repo / 'nix/contract-output.py'), str(source), str(baseline), str(config),
        str(specs), str(temporary / 'selected'), native['cast'], native['version']], capture_output=True, text=True)
    assert result.returncode != 0 and 'native compiler source hash mismatch' in result.stderr, result
    print(json.dumps({'case': 'stale-native-artifact-for-changed-source', 'exitCode': result.returncode,
                      'expectedDiagnostic': 'native compiler source hash mismatch'}), flush=True)
print('Native contract production ownership and compiler source-hash controls passed')
