from pathlib import Path
import zipfile, hashlib, json
root=Path.cwd();out=root/'outputs/residual-repair-20260928'
files={str(p.relative_to(root)):p.read_bytes() for p in sorted((root/'src').rglob('*.py'))}
for name in ['runtime_profiles.json','model.yaml','risk_conditioned_selective_v3.json']:
 files['configs/'+name]=(root/'configs'/name).read_bytes()
for name in ['remote_benchmark.py','remote_driver.py']:
 files[name]=(out/name).read_text().replace('/content/oa-repair','/content/oa-repair-final').encode()
files['baseline_answer_verifier.py']=(out/'baseline_answer_verifier.py').read_bytes()
files['verifier-contrasts.json']=(root/'docs/reviews/artifacts/portable-residual-20260928/verifier-contrasts.json').read_bytes()
manifest={'schema':'public_source_regression_capsule.v1','base_commit':'8380b8b','scope':'public source plus authorized repaired diff and synthetic fixture; no corpus or private artifacts','files':[{'path':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()} for name,data in files.items()]}
with zipfile.ZipFile(out/'capsule-final.zip','w',zipfile.ZIP_DEFLATED) as z:
 for name,data in files.items():z.writestr(name,data)
 z.writestr('manifest.json',json.dumps(manifest,indent=2))
(out/'capsule-final-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
launch=(out/'remote_launch.py').read_text().replace('/content/oa-repair','/content/oa-repair-final').replace('import json, subprocess, sys, zipfile','import json, subprocess, sys, zipfile, shutil').replace("assert not (root/'driver-pid.json').exists()", "shutil.copyfile('/content/oa-repair/setup.json',root/'setup.json')\nassert not (root/'driver-pid.json').exists()")
(out/'remote_launch_final.py').write_text(launch)
print(json.dumps({'files':len(files),'bytes':(out/'capsule-final.zip').stat().st_size,'sha256':hashlib.sha256((out/'capsule-final.zip').read_bytes()).hexdigest()}))
