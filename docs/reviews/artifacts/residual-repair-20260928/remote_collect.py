from pathlib import Path
import json, hashlib, zipfile
first=Path('/content/oa-repair'); final=Path('/content/oa-repair-final')
assert json.loads((first/'driver-done.json').read_text())['returncode']==0
assert json.loads((final/'driver-done.json').read_text())['returncode']==0
assert json.loads((final/'benchmark.json').read_text())['status']=='completed'
models=json.loads((first/'setup.json').read_text())['models']; hashes=[]
for model in models:
 rows=[]
 for path in sorted(Path(model['snapshot']).rglob('*')):
  if path.is_file():
   h=hashlib.sha256()
   with path.open('rb') as f:
    for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
   rows.append({'path':str(path.relative_to(model['snapshot'])),'bytes':path.stat().st_size,'sha256':h.hexdigest()})
 hashes.append({'repo':model['repo'],'revision':model['revision'],'files':rows})
(first/'snapshot-hashes.json').write_text(json.dumps(hashes,indent=2))
archive=Path('/content/oa-repair-results.zip')
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
 for label,root in [('first',first),('final',final)]:
  for name in ['runtime.json','setup.json','snapshot-hashes.json','benchmark.json','driver-pid.json','driver-done.json','benchmark.log','driver.log']:
   p=root/name
   if p.is_file():z.write(p,label+'/'+name)
print(json.dumps({'bytes':archive.stat().st_size,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest()}))
