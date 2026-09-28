import json, subprocess, sys, time, traceback
from pathlib import Path
root=Path('/content/oa-repair'); started=time.time()
try:
 with (root/'benchmark.log').open('w') as log:
  result=subprocess.run([sys.executable,str(root/'capsule/remote_benchmark.py')],stdout=log,stderr=subprocess.STDOUT,timeout=900)
 record={'started':started,'ended':time.time(),'returncode':result.returncode}
except subprocess.TimeoutExpired:
 record={'started':started,'ended':time.time(),'returncode':124,'status':'timeout'}
(root/'driver-done.json').write_text(json.dumps(record,indent=2))
