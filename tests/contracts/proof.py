"""Ordinary npm, pip, HTTP and Java consumers deploy native Solidity artifacts."""
from contextlib import contextmanager
import functools
import hashlib
import http.server
import importlib
import json
import os
from pathlib import Path
import select
import shutil
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import unquote, urlsplit
import urllib.error
import urllib.request
from xml.etree import ElementTree as ET
import zipfile

from web3 import Web3

spec = json.loads(Path(sys.argv[1]).read_text())
out = Path(sys.argv[2])
out.mkdir()


def sha(data):
    return hashlib.sha256(data).hexdigest()


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@contextmanager
def serve(root):
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(root)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield 'http://127.0.0.1:' + str(server.server_port)
    finally:
        server.shutdown(); server.server_close(); thread.join()


def npm_install(item, index):
    repository = Path(item['npm'])
    catalog = json.loads(Path(item['npmCatalog']).read_text())['modules']
    assert len(catalog) == 1
    module = catalog[0]
    assert module['name'] == '@fixture/counter-abi' and module['primary']

    class Registry(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            route = unquote(urlsplit(self.path).path).lstrip('/')
            if route == module['archive']:
                data = (repository / route).read_bytes()
            elif route == module['name']:
                metadata = dict(module['package'])
                metadata['dist'] = {'integrity': module['integrity'],
                    'tarball': 'http://' + self.headers['Host'] + '/' + module['archive']}
                data = json.dumps({'name': module['name'], 'versions': {module['version']: metadata},
                    'dist-tags': {'latest': module['version']}}).encode()
            else:
                self.send_error(404); return
            self.send_response(200); self.send_header('Content-Length', str(len(data)))
            self.end_headers(); self.wfile.write(data)

        def log_message(self, *args):
            pass

    project = Path.cwd() / ('npm-client-' + str(index))
    shutil.copytree(spec['nodeModules'], project, symlinks=True)
    for path in [project, *project.rglob('*')]:
        if not path.is_symlink():
            path.chmod(0o755 if path.is_dir() else 0o644)
    shutil.copyfile(Path(__file__).with_name('client.mjs'), project / 'client.mjs')
    shutil.copyfile(Path(__file__).with_name('client.ts'), project / 'client.ts')
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Registry)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        subprocess.run([spec['npm'], 'install', '--no-audit', '--no-fund', '--ignore-scripts', '--fetch-retries=0',
            '--registry', 'http://127.0.0.1:' + str(server.server_port) + '/', module['name'] + '@' + module['version']],
            cwd=project, env=dict(os.environ, npm_config_cache=str(project / 'cache')), check=True, timeout=120)
    finally:
        server.shutdown(); server.server_close(); thread.join()
    installed = project / 'node_modules/@fixture/counter-abi'
    metadata = json.loads((installed / 'package.json').read_text())
    assert metadata['version'] == module['version']
    assert metadata['exports']['.']['types'] == './main.d.ts'
    for path in Path(item['artifact']).iterdir():
        assert (installed / path.name).read_bytes() == path.read_bytes()
    subprocess.run([spec['typescript'], '--noEmit', '--strict', '--module', 'nodenext', '--target', 'es2022',
                    'client.ts'], cwd=project, check=True, timeout=60)
    return project, module['name'] + '@' + module['version']


def node_client(project, rpc, selected, resource, value):
    result = subprocess.run([spec['node'], 'client.mjs', rpc, selected, resource, str(value)],
        cwd=project, capture_output=True, text=True, check=True, timeout=60)
    assert not result.stderr, result.stderr
    return json.loads(result.stdout)


def python_install(item, index):
    catalog = json.loads(Path(item['pythonCatalog']).read_text())['modules']
    assert len(catalog) == 1
    module = catalog[0]
    installed = Path.cwd() / ('python-client-' + str(index))
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-index', '--no-deps', '--no-compile',
        '--find-links', item['python'], '--target', str(installed), module['name'] + '==' + module['version']],
        check=True, timeout=60)
    sys.path.insert(0, str(installed))
    sys.modules.pop('counter_abi', None)
    importlib.invalidate_caches()
    library = importlib.import_module('counter_abi')
    assert Path(library.__file__).resolve().is_relative_to(installed)
    for name in ['contract.json', 'abi.json', 'bytecode.json', 'deployed-bytecode.json']:
        assert (installed / 'counter_abi' / name).read_bytes() == (Path(item['artifact']) / name).read_bytes()
    return library, installed, module['name'] + '==' + module['version']


def python_client(web3, library, expected):
    factory = web3.eth.contract(abi=library.abi, bytecode=library.bytecode)
    receipt = web3.eth.wait_for_transaction_receipt(factory.constructor().transact())
    assert receipt.status == 1
    contract = web3.eth.contract(address=receipt.contractAddress, abi=library.abi)
    assert web3.eth.get_code(contract.address).hex().removeprefix('0x') == library.deployed_bytecode.removeprefix('0x')
    assert contract.functions.value().call() == expected
    assert contract.functions.distance(-17).call() == 18
    changed = web3.eth.wait_for_transaction_receipt(contract.functions.increment().transact())
    events = contract.events.Changed().process_receipt(changed)
    assert len(events) == 1 and events[0]['args']['value'] == expected + 1
    assert events[0]['args']['sender'] == web3.eth.default_account
    assert contract.functions.value().call() == expected + 1
    return {'initial': expected, 'after': expected + 1, 'distance': 18,
            'eventValue': events[0]['args']['value'], 'address': contract.address}


def resolve_webjar(repository, index):
    poms = list(repository.rglob('*.pom')); assert len(poms) == 1
    pom = ET.parse(poms[0]).getroot(); ns = {'m': 'http://maven.apache.org/POM/4.0.0'}
    group, artifact, version = [pom.find('m:' + key, ns).text for key in ['groupId', 'artifactId', 'version']]
    coordinate = ':'.join([group, artifact, version])
    project = Path.cwd() / ('gradle-' + str(index)); project.mkdir()
    report = project / 'resolved.txt'
    (project / 'config.json').write_text(json.dumps(dict(repository=str(repository), coordinate=coordinate, report=str(report))))
    (project / 'settings.gradle').write_text("rootProject.name='ordinary-contract-webjar-consumer'\n")
    (project / 'build.gradle').write_text('''def selected = new groovy.json.JsonSlurper().parse(file('config.json'))
repositories { maven { url=uri(selected.repository); metadataSources { mavenPom(); artifact() } } }
configurations { assets }
dependencies { assets(selected.coordinate) }
tasks.register('resolveAssets') { doLast { new File(selected.report).text=configurations.assets.singleFile.canonicalPath } }
''')
    subprocess.run(['gradle', '--offline', '--no-daemon', '--console=plain', 'resolveAssets'], cwd=project, check=True, timeout=180)
    resolved = Path(report.read_text())
    assert resolved.read_bytes() == poms[0].with_suffix('.jar').read_bytes()
    return resolved, coordinate, 'META-INF/resources/webjars/' + artifact + '/1.0.0/'


@contextmanager
def java_server(jar, prefix, manifest):
    process = subprocess.Popen(['java', 'ResourceServer', str(jar), prefix, str(manifest)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert select.select([process.stdout], [], [], 20)[0]
        yield 'http://127.0.0.1:' + str(int(process.stdout.readline().strip()))
    finally:
        process.terminate(); process.wait(timeout=10)
        assert not process.stderr.read()


with socket.socket() as reservation:
    reservation.bind(('127.0.0.1', 0)); port = reservation.getsockname()[1]
rpc = 'http://127.0.0.1:' + str(port)
anvil_log = (out / 'anvil.log').open('w')
anvil = subprocess.Popen([spec['anvil'], '--silent', '--host', '127.0.0.1', '--port', str(port)],
    stdout=anvil_log, stderr=subprocess.STDOUT)
try:
    web3 = Web3(Web3.HTTPProvider(rpc))
    for _ in range(100):
        if web3.is_connected(): break
        assert anvil.poll() is None
        time.sleep(0.1)
    assert web3.is_connected()
    web3.eth.default_account = web3.eth.accounts[0]
    subprocess.run(['javac', str(Path(__file__).with_name('ResourceConsumer.java')),
                    str(Path(__file__).with_name('ResourceServer.java')), '-d', '.'], check=True)
    rows = []; libraries = []; installed_python = []; projects = []
    for index, item in enumerate(spec['versions']):
        native = Path(item['artifact']); web = Path(item['web']); files = web / 'files'
        model = json.loads((Path(item['proof']) / 'model.json').read_text())
        expected = model['files']
        assert set(expected) == {'contract.json', 'abi.json', 'bytecode.json', 'deployed-bytecode.json', 'main.mjs', 'main.d.ts'}
        assert any(s['owner'] == 'project' for s in model['sources'].values())
        assert any(s['owner'] == 'locked-dependency' for s in model['sources'].values())
        assert model['sources']['interfaces/OwnMath.sol']['owner'] == 'project'
        assert not any('Private.sol' in name for name in model['sources'])
        native_forge = Path(item['native']) / model['artifact']
        original = Path(item['unprojectedNative'])
        actual_tree = {str(p.relative_to(Path(item['native']))): sha(p.read_bytes())
                       for p in Path(item['native']).rglob('*') if p.is_file()}
        original_tree = {str(p.relative_to(original)): sha(p.read_bytes())
                         for p in original.rglob('*') if p.is_file()}
        assert actual_tree == original_tree, 'projection changed the native Forge output tree'
        assert native_forge.read_bytes() == (native / 'contract.json').read_bytes()
        assert sha(native_forge.read_bytes()) == model['artifactSha256']
        for root in [native, files]:
            assert {p.name for p in root.iterdir()} == set(expected)
            assert all(sha((root / name).read_bytes()) == checksum for name, checksum in expected.items())
        library, installed, python_coordinate = python_install(item, index)
        libraries.append(library); installed_python.append(installed)
        python_result = python_client(web3, library, item['value'])
        project, npm_coordinate = npm_install(item, index); projects.append(project)
        direct = node_client(project, rpc, (native / 'main.mjs').as_uri(), '-', item['value'])
        with serve(files) as url:
            for name, checksum in expected.items():
                assert sha(urllib.request.urlopen(url + '/' + name, timeout=10).read()) == checksum
            for forbidden in ['private.txt', 'Private.sol/Private.json', 'proof/model.json', 'contract-proof/counter/model.json']:
                try: urllib.request.urlopen(url + '/' + forbidden, timeout=10)
                except urllib.error.HTTPError as error: assert error.code == 404
                else: raise AssertionError('private compiler/source file exposed')
            http_result = node_client(project, rpc, '@fixture/counter-abi', url, item['value'])
        manifest = out / ('resources-' + str(index) + '.tsv')
        manifest.write_text(''.join(name + '\t' + checksum + '\n' for name, checksum in sorted(expected.items())))
        resource_java = subprocess.check_output(['java', 'ResourceConsumer', str(web / 'resources.jar'), str(manifest), ''], text=True)
        jar, coordinate, prefix = resolve_webjar(Path(item['maven']), index)
        java = subprocess.check_output(['java', 'ResourceConsumer', str(jar), str(manifest), prefix], text=True)
        with zipfile.ZipFile(jar) as archive:
            assert not any('private.txt' in name or 'contract-proof/' in name for name in archive.namelist())
            for name, checksum in expected.items(): assert sha(archive.read(prefix + name)) == checksum
        with java_server(jar, prefix, manifest) as url:
            java_http = node_client(project, rpc, '@fixture/counter-abi', url, item['value'])
        (out / ('java-' + str(index) + '.txt')).write_text(resource_java + java)
        rows.append(dict(value=item['value'], files=expected, compiler=model['compiler'], sources=model['sources'],
            npmCoordinate=npm_coordinate, pythonCoordinate=python_coordinate, webjarCoordinate=coordinate,
            python=python_result, native=direct, http=http_result, javaHTTP=java_http))
    for key in ['npmCoordinate', 'pythonCoordinate', 'webjarCoordinate']:
        assert rows[0][key] != rows[1][key]
    # A genuine independently compiled replacement deploys the changed source value.
    replacement = web3.eth.contract(abi=libraries[0].abi, bytecode=libraries[1].bytecode)
    receipt = web3.eth.wait_for_transaction_receipt(replacement.constructor().transact())
    changed = web3.eth.contract(address=receipt.contractAddress, abi=libraries[0].abi)
    assert changed.functions.value().call() == 43 and changed.functions.value().call() != 42
    assert rows[0]['files']['contract.json'] != rows[1]['files']['contract.json']
    missing = Path.cwd() / 'missing-python-resource'
    shutil.copytree(installed_python[0] / 'counter_abi', missing / 'counter_abi')
    (missing / 'counter_abi/contract.json').unlink()
    failed = subprocess.run([sys.executable, '-c', 'import counter_abi'], cwd=missing,
        env=dict(os.environ, PYTHONPATH=str(missing)), capture_output=True, text=True)
    assert failed.returncode != 0 and 'contract.json' in failed.stderr
    (projects[0] / 'node_modules/@fixture/counter-abi/main.mjs').unlink()
    failed = subprocess.run([spec['node'], '--input-type=module', '-e', 'import "@fixture/counter-abi"'],
        cwd=projects[0], capture_output=True, text=True)
    assert failed.returncode != 0 and 'main.mjs' in failed.stderr
    (out / 'proof.json').write_text(json.dumps({'versions': rows, 'controls': {
        'nativeReplacement': 'compiled43 deploys43 and fails original42 expectation',
        'missingResources': 'ordinary Python and Node imports fail',
        'privateSources': 'HTTP404 and absent from resource/WebJar roots'}}, sort_keys=True, indent=2) + '\n')
finally:
    anvil.terminate(); anvil.wait(timeout=10); anvil_log.close()
print('Native Solidity ABI / npm+TypeScript+ethers / Python+Web3 / HTTP+Java+Gradle consumers passed')
