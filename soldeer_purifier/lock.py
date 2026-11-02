# SPDX-License-Identifier: MIT
"""Validate the native lock without duplicating its coordinates."""
import hashlib,json,re,tomllib
from pathlib import Path
FIX='; run soldeer-purifier lock'
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def seal(data):
 data={k:v for k,v in data.items() if k!='contentHash'}
 return {**data,'contentHash':hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()}
def install_name(entry):
 name=entry['name'];version=entry['version']
 for value in (name,version):
  if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9@_.+-]+',value) or value in ('.','..'):raise ValueError('unsupported dependency name/version'+FIX)
 path=f'{name}-{version}'
 if len(path.encode())>240:raise ValueError('dependency path too long'+FIX)
 return path
def records(native):
 data=tomllib.loads(Path(native).read_text())
 if data.get('version')!=2:raise ValueError('expected Soldeer 0.12 lock format 2'+FIX)
 entries=data.get('dependencies',[])
 if not isinstance(entries,list):raise ValueError('invalid native dependencies'+FIX)
 paths=set()
 for entry in entries:
  path=install_name(entry)
  if path in paths:raise ValueError('duplicate dependency path'+FIX)
  paths.add(path)
  if 'git' in entry:
   if not isinstance(entry['git'],str) or not re.fullmatch('[0-9a-f]{40}',entry.get('rev','')):raise ValueError('invalid Git lock'+FIX)
  elif 'url' in entry:
   if not re.fullmatch(r'https?://[^/@\s]+/[^\s]*',entry['url']):raise ValueError('invalid archive URL'+FIX)
   if not all(re.fullmatch('[0-9a-f]{64}',entry.get(k,'')) for k in ('checksum','integrity')):raise ValueError('invalid native checksum'+FIX)
  else:raise ValueError('private packages without immutable download URLs are unsupported'+FIX)
 return entries
def config_path(root):
 found=[root/n for n in ('foundry.toml','soldeer.toml') if (root/n).is_file()]
 if len(found)!=1:raise ValueError('use exactly one foundry.toml or soldeer.toml'+FIX)
 return found[0]
def inputs(root):return {p.name:digest(p) for p in (root/'foundry.toml',root/'soldeer.toml',root/'remappings.txt') if p.is_file()}
def configuration(root):
 p=config_path(root);data=tomllib.loads(p.read_text())
 if data.get('soldeer',{}).get('recursive_deps',False):raise ValueError('recursive dependency installation is not supported yet'+FIX)
 return p,data
def problems(root,native,data):
 try:
  _,config=configuration(root);entries=records(native)
  if not isinstance(data,dict) or data.get('version')!=1:return ['unsupported companion format'+FIX]
  if data.get('contentHash')!=seal(data)['contentHash']:return ['contentHash mismatch'+FIX]
  if data.get('inputs')!=inputs(root) or data.get('nativeHash')!=digest(native):return ['configuration or native lock changed'+FIX]
  metadata=data.get('dependencies')
  if not isinstance(metadata,dict) or set(metadata)!={install_name(e) for e in entries}:return ['missing dependency metadata'+FIX]
  if set(config.get('dependencies',{}))!={e['name'] for e in entries}:return ['native lock does not match dependency declarations'+FIX]
  for e in entries:
   m=metadata[install_name(e)]
   if 'git' in e:
    if not isinstance(m.get('commitObject'),dict) or not isinstance(m['commitObject'].get('object'),str) or not isinstance(m['commitObject'].get('gitlinks'),list) or not re.fullmatch(r'sha256-[A-Za-z0-9+/]{43}=',m.get('hash','')):return ['missing Git NAR hash'+FIX]
   elif not isinstance(m.get('stripTop'),bool):return ['missing extraction metadata'+FIX]
  return []
 except (ValueError,KeyError,TypeError,OSError) as e:return [str(e)+FIX]
