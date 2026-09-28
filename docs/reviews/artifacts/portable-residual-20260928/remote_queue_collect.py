import json,subprocess,sys
from pathlib import Path
root=Path('/content/oa-residual')
assert not (root/'followup-pid.json').exists(),'Never duplicate a queued followup'
with (root/'followup-driver.log').open('w') as log:
 p=subprocess.Popen([sys.executable,str(root/'remote_followup_collect.py')],stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
(root/'followup-pid.json').write_text(json.dumps({'pid':p.pid}))
print(json.dumps({'pid':p.pid,'waits_for':'driver-done.json','max_probe_seconds':180}))
