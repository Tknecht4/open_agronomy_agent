import hashlib,json,os,subprocess,sys,time,zipfile
from pathlib import Path
root=Path('/content/oa-residual');root.mkdir(exist_ok=True)
archive=Path('/content/oa-residual-capsule.zip')
with zipfile.ZipFile(archive) as z:z.extractall(root/'capsule')
capsule=root/'capsule'
plan=json.loads((capsule/'experiment-plan.json').read_text())
setup=json.loads((root/'setup.json').read_text())
assert len(setup['models'])==2
results=[]
(root/'driver-start.json').write_text(json.dumps({'start_unix':time.time(),'capsule_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'plan':plan},indent=2))
for model in setup['models']:
 name='gemma' if 'gemma' in model['repo'] else 'qwen'
 ledger=capsule/('gemma-v3-cells.jsonl.gz' if name=='gemma' else 'qwen27b-v4-cells.jsonl.gz')
 for arm in ['active','method_candidate']:
  task=f'cache-{name}-{arm}'
  cmd=[sys.executable,str(capsule/'cache_probe.py'),'--ledger',str(ledger),'--unit',f'cache/{arm}/PFMH3-01','--output',str(root/task),'--execute','--snapshot',model['snapshot'],'--max-tokens','320']
  begin=time.time()
  with (root/(task+'.log')).open('w') as log:
   try:r=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,timeout=720);code=r.returncode
   except subprocess.TimeoutExpired:code=124
  results.append({'task':task,'start_unix':begin,'end_unix':time.time(),'returncode':code});(root/'driver-status.json').write_text(json.dumps(results,indent=2));print(results[-1],flush=True)
  if code:break
 task=f'budget-{name}';cmd=[sys.executable,str(capsule/'budget_probe.py'),'--ledger',str(ledger),'--snapshot',model['snapshot'],'--output',str(root/task)];begin=time.time()
 with (root/(task+'.log')).open('w') as log:
  try:r=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,timeout=600);code=r.returncode
  except subprocess.TimeoutExpired:code=124
 results.append({'task':task,'start_unix':begin,'end_unix':time.time(),'returncode':code});(root/'driver-status.json').write_text(json.dumps(results,indent=2));print(results[-1],flush=True)
(root/'driver-done.json').write_text(json.dumps({'end_unix':time.time(),'results':results},indent=2))
