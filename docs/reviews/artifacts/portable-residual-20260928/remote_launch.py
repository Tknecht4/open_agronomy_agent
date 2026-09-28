import json,subprocess,sys,zipfile
from pathlib import Path
root=Path('/content/oa-residual');root.mkdir(exist_ok=True)
assert not (root/'driver-pid.json').exists(), 'Do not duplicate an existing driver'
with zipfile.ZipFile('/content/oa-residual-capsule.zip') as z:z.extractall(root/'capsule')
with (root/'driver.log').open('w') as log:
 p=subprocess.Popen([sys.executable,str(root/'capsule/remote_run.py')],stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
(root/'driver-pid.json').write_text(json.dumps({'pid':p.pid}))
print(json.dumps({'pid':p.pid,'root':str(root)}))
