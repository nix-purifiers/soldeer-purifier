# SPDX-License-Identifier: MIT
import base64,argparse,fcntl,hashlib,json,os,shutil,subprocess,sys,tempfile,urllib.request,zipfile
from pathlib import Path
from . import lock
FORGE=os.environ.get('SOLDEER_PURIFIER_FORGE','forge')
def run(args,**kwargs):return subprocess.run(list(map(str,args)),check=True,**kwargs)
def load(path):return json.loads(path.read_text())
def write(path,text):
 path.parent.mkdir(parents=True,exist_ok=True)
 temp=path.with_name(path.name+'.new');temp.write_text(text);temp.replace(path)
def checked(root,native,sidecar):
 try:data=load(sidecar);errors=lock.problems(root,native,data)
 except (ValueError,OSError) as e:raise ValueError(str(e)+lock.FIX) from e
 if errors:raise ValueError('\n'.join(errors))
 return data
IGNORE=shutil.ignore_patterns('.git','dependencies','.soldeer-purifier','out','cache','broadcast','result','__pycache__')
def realize(root,native,sidecar,target):
 args=['nix','build','--impure','--file',os.environ['SOLDEER_PURIFIER_REALIZE'],'--argstr','project',root,'--argstr','lockFile',sidecar,'--argstr','soldeerLock',native,'--argstr','target',target,'--no-link','--print-out-paths']
 return Path(run(args,text=True,stdout=subprocess.PIPE).stdout.strip())
def do_lock(root,native,sidecar,update=False):
 config,data=lock.configuration(root)
 if sidecar.exists() and not update:
  try:
   previous=checked(root,native,sidecar)
   if previous['forgeVersion']==os.environ.get('SOLDEER_PURIFIER_FORGE_VERSION') and previous['solcVersion']==os.environ.get('SOLDEER_PURIFIER_SOLC_VERSION'):
    print('Existing native resolution retained');return
  except ValueError:pass
 with tempfile.TemporaryDirectory(prefix='soldeer-lock-') as tmp:
  stage=Path(tmp)/'project';shutil.copytree(root,stage,ignore=IGNORE)
  target=stage/'soldeer.lock'
  if native.exists():shutil.copyfile(native,target)
  elif (root/'soldeer.lock').exists():shutil.copyfile(root/'soldeer.lock',target)
  # Native install respects its existing lock, including moved Git branches.
  location='foundry' if config.name=='foundry.toml' else 'soldeer'
  existing=lock.records(target) if target.exists() else []
  if target.exists() and (update or not existing):target.unlink()
  elif target.exists():
   selected={e['name'] for e in existing}
   for name,declaration in data.get('dependencies',{}).items():
    if name in selected:continue
    spec={'version':declaration} if isinstance(declaration,str) else declaration
    command=[FORGE,'soldeer','install',name+'~'+spec['version'],'--config-location',location]
    for key in ('url','git','rev','branch','tag'):
     if key in spec:command.extend(['--'+key,spec[key]])
    run(command,cwd=stage)
  run([FORGE,'soldeer','install','--config-location',location],cwd=stage)
  if update:run([FORGE,'soldeer','update','--config-location',location],cwd=stage)
  entries=lock.records(target);metadata={}
  for entry in entries:
   name=lock.install_name(entry)
   if 'git' in entry:
    info=json.loads(run(['nix-prefetch-git','--url',entry['git'],'--rev',entry['rev'],'--fetch-submodules'],text=True,capture_output=True).stdout)
    value=run(['nix','hash','convert','--hash-algo','sha256','--to','sri',info['sha256']],text=True,capture_output=True).stdout.strip()
    checkout=stage/'dependencies'/name
    obj=run(['git','-C',checkout,'cat-file','commit',entry['rev']],capture_output=True).stdout
    tree=run(['git','-C',checkout,'ls-tree','-rz',entry['rev']],capture_output=True).stdout
    links=[]
    for record in tree.split(b'\0'):
     if record:
      header,path=record.split(b'\t',1);mode,kind,rev=header.split()
      if mode==b'160000':links.append({'path':path.decode(),'rev':rev.decode()})
    metadata[name]={'hash':value,'commitObject':{'object':base64.b64encode(obj).decode(),'gitlinks':links}}
   else:
    declaration=data['dependencies'][entry['name']]
    custom=isinstance(declaration,dict) and 'url' in declaration
    strip=False
    if custom:
     archive=Path(tmp)/'package.zip'
     with urllib.request.urlopen(entry['url']) as response:archive.write_bytes(response.read())
     if lock.digest(archive)!=entry['checksum']:raise ValueError('native archive checksum mismatch'+lock.FIX)
     with zipfile.ZipFile(archive) as z:
      names=[n for n in z.namelist() if n and '.git' not in n.split('/') and not n.startswith('__MACOSX/')]
      first={n.split('/')[0] for n in names}
      strip=len(first)==1 and all('/' in n for n in names)
    metadata[name]={'stripTop':strip}
  write(native,target.read_text())
  if (stage/'remappings.txt').exists():write(root/'remappings.txt',(stage/'remappings.txt').read_text())
  result=lock.seal({'version':1,'nativeHash':lock.digest(native),'inputs':lock.inputs(root),'forgeVersion':os.environ['SOLDEER_PURIFIER_FORGE_VERSION'],'solcVersion':os.environ['SOLDEER_PURIFIER_SOLC_VERSION'],'dependencies':metadata})
  errors=lock.problems(root,native,result)
  if errors:raise ValueError('\n'.join(errors))
  write(sidecar,json.dumps(result,indent=2,sort_keys=True)+'\n')
def prefetch(root,native,sidecar):
 data=checked(root,native,sidecar)
 cache=sidecar.parent/'.soldeer-purifier'/hashlib.sha256(str(sidecar).encode()).hexdigest()[:12]
 cache.mkdir(parents=True,exist_ok=True)
 # Keep both the dependency closure and the complete native toolchain alive.
 for target in ('dependencies','runtime'):
  out=realize(root,native,sidecar,target);link=cache/target
  run(['nix-store','--add-root',link,'--indirect','--realise',out],stdout=subprocess.DEVNULL)
 dependencies=root/'dependencies'
 if dependencies.is_symlink():raise ValueError('dependencies must be a directory'+lock.FIX)
 dependencies.mkdir(exist_ok=True)
 state_dir=root/'.soldeer-purifier';state_dir.mkdir(exist_ok=True)
 with (state_dir/'materialize.lock').open('a') as stream:
  fcntl.flock(stream,fcntl.LOCK_EX)
  state_path=state_dir/'managed.json';managed=load(state_path) if state_path.exists() else {}
  for name in sorted(set(managed)-set(data['dependencies'])):
   dest=dependencies/name
   if dest.is_dir() and not dest.is_symlink():
    if tree_hash(dest)!=managed[name]['digest']:raise ValueError(f'removed dependency modified: {dest}; move it aside before prefetching')
    for p in [dest,*dest.rglob('*')]:
     if not p.is_symlink():p.chmod(p.stat().st_mode|0o200)
    shutil.rmtree(dest)
   del managed[name]
  write(state_path,json.dumps(managed,sort_keys=True))
  for name in data['dependencies']:
   dest=dependencies/name;source=(cache/'dependencies'/name).resolve()
   if name in managed and dest.is_dir() and not dest.is_symlink():
    if tree_hash(dest)!=managed[name]['digest']:raise ValueError(f'locked dependency modified: {dest}; move it aside and prefetch again')
    if managed[name]['source']==str(source):continue
    for p in [dest,*dest.rglob("*")]:
     if not p.is_symlink():p.chmod(p.stat().st_mode|0o200)
    shutil.rmtree(dest)
   elif dest.exists() or dest.is_symlink():
    backup=dest.with_name(dest.name+'.before-purifier')
    if backup.exists() or backup.is_symlink():raise ValueError(f'existing backup: {backup}')
    dest.rename(backup)
   shutil.copytree(source,dest,symlinks=True)
   managed[name]={'source':str(source),'digest':tree_hash(dest)}
   write(state_path,json.dumps(managed,sort_keys=True))

 return data
def tree_hash(root):
 hasher=hashlib.sha256()
 for path in sorted(root.rglob('*')):
  if '.git' in path.relative_to(root).parts:continue
  if path.is_symlink():body=b'link\0'+os.readlink(path).encode()
  elif path.is_file():body=b'file\0'+str(path.stat().st_mode&0o111).encode()+b'\0'+path.read_bytes()
  else:body=b'directory'
  hasher.update(hashlib.sha256(str(path.relative_to(root)).encode()+b'\0'+body).digest())
 return hasher.hexdigest()

def restore(root):
 state=root/'.soldeer-purifier/managed.json'
 if not state.exists():return
 for name in load(state):
  dest=root/'dependencies'/name;backup=dest.with_name(dest.name+'.before-purifier')
  # Keep materialized dependency files as the native cache on fallback.
  if dest.is_dir() and not dest.is_symlink():
   for p in [dest,*dest.rglob('*')]:
    if not p.is_symlink():p.chmod(p.stat().st_mode|0o200)
 state.unlink()
def native_command(root,native,sidecar,args):
 if not sidecar.exists():
  print('soldeer-purifier: no lockfile; using ordinary impure Forge',file=sys.stderr)
  restore(root)
  os.chdir(root)
  os.execv(FORGE,[FORGE,*args])
 checked(root,native,sidecar)
 command=next((arg for arg in args if arg in ('build','test','snapshot','coverage','script','create','inspect','flatten','soldeer','install','update','remove','init')),None)
 if command in ('install','update','remove','init'):raise ValueError('change dependencies through soldeer-purifier lock/update')
 if command=='soldeer':
  args_index=args.index('soldeer');soldeer_args=args[args_index+1:]
  if soldeer_args==['install']:prefetch(root,native,sidecar);return
  if soldeer_args and soldeer_args[0] not in ('version','help','--help','-h'):raise ValueError('change dependencies through soldeer-purifier lock/update')
 if command in ('build','test','snapshot','coverage','script','create','inspect','flatten'):
  prefetch(root,native,sidecar)
  if any(a=='--use' or a.startswith('--use=') or a=='--online' for a in args):raise ValueError('locked builds use the Nix-provided compiler')
  args=[*args,'--offline','--use',os.environ['SOLDEER_PURIFIER_SOLC']]
 os.chdir(root);os.execv(FORGE,[FORGE,*args])
def main():
 p=argparse.ArgumentParser();p.add_argument('--project',default='.');p.add_argument('--lockfile',default=os.environ.get('SOLDEER_PURIFIER_LOCKFILE'));p.add_argument('--soldeer-lock',default=os.environ.get('SOLDEER_PURIFIER_SOLDEER_LOCK'))
 sub=p.add_subparsers(dest='command',required=True)
 for command in ('lock','update','prefetch'):sub.add_parser(command)
 n=sub.add_parser('native');n.add_argument('args',nargs=argparse.REMAINDER)
 pub=sub.add_parser('publish');pub.add_argument('--repo',required=True);pub.add_argument('--tag',required=True)
 a=p.parse_args();root=Path(a.project).resolve()
 if a.command=='native':
  a.args=a.args[1:] if a.args[:1]==['--'] else a.args
  for index,value in enumerate(a.args):
   if value=='--root' and index+1<len(a.args):
    root=Path(a.args[index+1]).resolve();a.args[index+1]=str(root)
   elif value.startswith('--root='):
    root=Path(value.split('=',1)[1]).resolve();a.args[index]='--root='+str(root)
 if a.command=='native' and a.project=='.' and not any(arg=='--root' or arg.startswith('--root=') for arg in a.args):
  root=next((candidate for candidate in [root,*root.parents] if any((candidate/name).is_file() for name in ('foundry.toml','soldeer.toml'))),root)
 native=Path(a.soldeer_lock).resolve() if a.soldeer_lock else root/'soldeer.lock'
 sidecar=Path(a.lockfile).resolve() if a.lockfile else root/'soldeer-purifier.lock.json'
 try:
  if a.command in ('lock','update'):do_lock(root,native,sidecar,a.command=='update')
  elif a.command=='prefetch':prefetch(root,native,sidecar)
  elif a.command=='native':native_command(root,native,sidecar,a.args[1:] if a.args[:1]==['--'] else a.args)
  else:
   checked(root,native,sidecar);artifact=realize(root,native,sidecar,'release')
   run(['gh','release','create',a.tag,*sorted(artifact.iterdir()),'--repo',a.repo,'--title',a.tag,'--generate-notes'])
 except (ValueError,OSError,subprocess.CalledProcessError) as e:p.exit(1,f'soldeer-purifier: {e}{lock.FIX}\n')
if __name__=='__main__':main()
