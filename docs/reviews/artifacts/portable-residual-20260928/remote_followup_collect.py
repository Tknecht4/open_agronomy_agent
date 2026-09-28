import hashlib,json,subprocess,sys,time,zipfile
from pathlib import Path
root=Path('/content/oa-residual')
deadline=time.monotonic()+1200
while not (root/'driver-done.json').exists():
 if time.monotonic()>deadline:raise TimeoutError('Base driver not complete within collection wait bound')
 time.sleep(3)
setup=json.loads((root/'setup.json').read_text());gemma=next(m for m in setup['models'] if 'gemma' in m['repo'])
cmd=[sys.executable,str(root/'cache_same_origin_probe.py'),'--receipt',str(root/'cache-gemma-active/cache-runtime.json'),'--snapshot',gemma['snapshot'],'--output',str(root/'same-origin-gemma-active'),'--execute','--max-tokens','8','--timeout-seconds','180']
start=time.time()
with (root/'same-origin.log').open('w') as log:
 try:r=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,timeout=180);code=r.returncode
 except subprocess.TimeoutExpired:code=124
(root/'followup-status.json').write_text(json.dumps({'start_unix':start,'end_unix':time.time(),'returncode':code,'external_timeout_seconds':180},indent=2))
manifests=[]
from mlx_lm.utils import load_tokenizer
for model in setup['models']:
 snapshot=Path(model['snapshot']);files=[]
 for f in sorted(snapshot.rglob('*')):
  if not f.is_file():continue
  h=hashlib.sha256()
  with f.open('rb') as handle:
   while block:=handle.read(8*1024*1024):h.update(block)
  files.append({'path':str(f.relative_to(snapshot)),'bytes':f.stat().st_size,'sha256':h.hexdigest()})
 config=json.loads((snapshot/'config.json').read_text())
 tok=load_tokenizer(snapshot,eos_token_ids=config.get('eos_token_id'))
 manifests.append({'repo':model['repo'],'revision':model['revision'],'files':files,'eos_token_ids':sorted(tok.eos_token_ids)})
(root/'snapshot-file-manifests.json').write_text(json.dumps(manifests,indent=2))
(root/'collection-done.json').write_text(json.dumps({'end_unix':time.time()}))
with zipfile.ZipFile('/content/oa-residual-results.zip','w',zipfile.ZIP_DEFLATED) as z:
 for f in sorted(root.rglob('*')):
  if f.is_file() and 'capsule' not in f.relative_to(root).parts:z.write(f,str(f.relative_to(root)))
 z.write('/content/oa-residual-runtime.json','runtime-preinstall.json')
print('collection completed',flush=True)
