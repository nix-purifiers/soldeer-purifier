# SPDX-License-Identifier: MIT
"""Exercise native Git resolution, moved refs, external locks and offline builds."""
import functools,http.server,io,json,os,shutil,socket,subprocess,sys,tempfile,threading,time,tomllib,urllib.request,zipfile
from pathlib import Path
SOURCE=Path(__file__).resolve().parents[1]
def run(args,**kwargs):return subprocess.run(list(map(str,args)),check=True,text=True,**kwargs)
case=sys.argv[1]
with tempfile.TemporaryDirectory(prefix='soldeer-conformance-') as tmp:
 temp=Path(tmp);run(['nix','build',SOURCE,'--out-link',temp/'cli'])
 cli=temp/'cli/bin/soldeer-purifier';forge=temp/'cli/bin/forge'
 root=temp/'project';root.mkdir();native=temp/'locks/native.toml' if case in ('external','git','custom') else root/'soldeer.lock';sidecar=temp/'locks/companion.json' if case in ('external','git','custom') else root/'soldeer-purifier.lock.json'
 def purifier(command):return run([cli,'--project',root,'--soldeer-lock',native,'--lockfile',sidecar,command])
 daemon=None;httpd=None
 if case in ('external','git','custom'):
  shutil.copytree(SOURCE/'examples/counter',root,dirs_exist_ok=True,ignore=shutil.ignore_patterns('dependencies','out','cache','.soldeer-purifier','soldeer-purifier.lock.json'))
  native.parent.mkdir();shutil.copyfile(root/'soldeer.lock',native)
  (root/'soldeer.lock').write_text('# deliberately different working copy\nversion = 2\n')
  original=(root/'soldeer.lock').read_bytes()
  if case in ('git','custom'):
   config=(root/'foundry.toml').read_text()
   if case=='git':declaration='{ version="1.11.0", git="https://github.com/foundry-rs/forge-std.git", tag="v1.11.0" }'
   else:
    entry=tomllib.loads(native.read_text())['dependencies'][0]
    with urllib.request.urlopen(entry['url']) as response:payload=response.read()
    with zipfile.ZipFile(io.BytesIO(payload)) as original_zip,zipfile.ZipFile(temp/'package.zip','w') as archive:
     for name in original_zip.namelist():
      if not name.endswith('/'):archive.writestr('wrapped/'+name,original_zip.read(name))
    handler=functools.partial(http.server.SimpleHTTPRequestHandler,directory=temp)
    httpd=http.server.ThreadingHTTPServer(('127.0.0.1',0),handler)
    threading.Thread(target=httpd.serve_forever,daemon=True).start()
    declaration='{ version="1.11.0", url="http://127.0.0.1:'+str(httpd.server_port)+'/package.zip" }'
   (root/'foundry.toml').write_text(config.replace('forge-std = "1.11.0"','forge-std = '+declaration))
   native.write_text('version = 2\ndependencies = []\n')

 else:
  repo=temp/'module';repo.mkdir();run(['git','init','-b','main',repo]);run(['git','-C',repo,'config','user.name','Tests']);run(['git','-C',repo,'config','user.email','tests@example.invalid'])
  def commit(value):
   (repo/'Value.sol').write_text(f'// SPDX-License-Identifier: MIT\npragma solidity ^0.8.33;\nlibrary Value {{ function number() internal pure returns (uint256) {{ return {value}; }} }}\n')
   run(['git','-C',repo,'add','.']);run(['git','-C',repo,'commit','-m',str(value)])
   return run(['git','-C',repo,'rev-parse','HEAD'],capture_output=True).stdout.strip()
  first=commit(1)
  (root/'foundry.toml').write_text(f'[profile.default]\nsolc = "0.8.33"\nlibs = ["dependencies"]\n[dependencies]\nsample = {{ version="1", git="file://{repo}", branch="main" }}\n[soldeer]\nremappings_generate = true\nrecursive_deps = false\n')
  (root/'src').mkdir();(root/'src/Main.sol').write_text('// SPDX-License-Identifier: MIT\npragma solidity ^0.8.33;\nimport {Value} from "sample-1/Value.sol";\ncontract Main { function value() external pure returns (uint256) { return Value.number(); } }\n')
 try:
  purifier('lock');before=sidecar.read_bytes();old_native=native.read_bytes()
  purifier('lock');assert sidecar.read_bytes()==before and native.read_bytes()==old_native
  if case in ('relock','update'):
   second=commit(2)
   if case=='relock':
    (root/'foundry.toml').write_text((root/'foundry.toml').read_text()+'\n')
    purifier('lock');assert 'rev = "'+first+'"' in native.read_text()
   else:
    purifier('update');assert 'rev = "'+second+'"' in native.read_text()
   sidecar.write_text('{broken');purifier('lock')
  if case in ('relock','update'):
   print(case+': native file-repository pins retained/updated; network-free builds covered by the public fixture')
   sys.exit(0)
  purifier('prefetch')
  if daemon:daemon.terminate();daemon.wait();daemon=None
  if httpd:httpd.shutdown();httpd.server_close();httpd=None
  env={**os.environ,'SOLDEER_PURIFIER_LOCKFILE':str(sidecar),'SOLDEER_PURIFIER_SOLDEER_LOCK':str(native)}
  run([forge,'build'],cwd=root,env=env);run([forge,'test'],cwd=root,env=env)
  assert not list(root.glob('*.nix'))
  if case in ('external','git','custom'):
   assert (root/'soldeer.lock').read_bytes()==original
   assert native.read_bytes()==old_native and sidecar.read_bytes()==before
   run(['nix','build','--impure','--file',temp/'cli/lib/soldeer-purifier/nix/realize.nix','--argstr','project',root,'--argstr','lockFile',sidecar,'--argstr','soldeerLock',native,'--argstr','target','release','--no-link'])
  sidecar.unlink()
  result=run([forge,'--version'],cwd=root,env=env,capture_output=True)
  assert 'ordinary impure Forge' in result.stderr
 finally:
  if httpd:httpd.shutdown();httpd.server_close()
  if daemon:daemon.terminate();daemon.wait()
print(case+': native resolution and offline builds pass')
