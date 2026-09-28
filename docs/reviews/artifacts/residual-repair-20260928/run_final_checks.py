import hashlib,json,os,subprocess,time,sys
from pathlib import Path
root=Path.cwd();out=root/'outputs/residual-repair-20260928';manifest=root/'docs/reviews/artifacts/residual-repair-20260928/review-candidate.json'
candidate=json.loads(manifest.read_text())
def verify():
 for r in candidate['runtime_and_tests']:assert hashlib.sha256(Path(r['path']).read_bytes()).hexdigest()==r['sha256'],r['path']
verify();begin=time.time();env=dict(os.environ,PYTHONPATH='src');cmd=[str(root/'.venv/bin/python'),'-m','pytest','-q']
with (out/'full-python-accepted-source.log').open('w') as log:r=subprocess.run(cmd,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=600)
verify();content=(out/'full-python-accepted-source.log').read_text();summary=content.strip().splitlines()[-1]
receipt={'schema':'integrated_checks.v1','candidate_digest':candidate['sha256'],'source_verified_before_and_after':True,'python':sys.version,'command':'PYTHONPATH=src .venv/bin/python -m pytest -q','returncode':r.returncode,'seconds':time.time()-begin,'summary':summary,'log_sha256':hashlib.sha256(content.encode()).hexdigest()}
(out/'integrated-checks.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt));sys.exit(r.returncode)
