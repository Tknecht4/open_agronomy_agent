import os
os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN'] = '1'
import json, time, importlib.metadata, hashlib
from pathlib import Path
import mlx.core as mx
from huggingface_hub import snapshot_download
out = Path('/content/oa-residual'); out.mkdir(exist_ok=True)
r = {'start_unix': time.time(), 'packages': {p: importlib.metadata.version(p) for p in ('mlx', 'mlx-lm', 'mlx-vlm', 'transformers', 'huggingface-hub')}, 'default_device': str(mx.default_device()), 'gpu_count': mx.device_count(mx.gpu), 'models': []}
assert r['gpu_count'] > 0
x = mx.ones((32,32)); y = x @ x; mx.eval(y)
assert float(y[0,0]) == 32.0
r['matmul_passed'] = True
(out/'setup.json').write_text(json.dumps(r, indent=2))
print(json.dumps(r), flush=True)
for repo, rev in [('mlx-community/gemma-4-e2b-it-4bit','238767527555cb75a05732a84dff5d6ba0dd6809'), ('mlx-community/Qwen3.5-27B-4bit','45797d2985a12c55e6473686e9ea91b95e959553')]:
    start = time.time()
    path = snapshot_download(repo, revision=rev, cache_dir='/content/oa-hf/hub', token=False)
    offline = snapshot_download(repo, revision=rev, cache_dir='/content/oa-hf/hub', local_files_only=True, token=False)
    assert path == offline
    files = [{'path': str(f.relative_to(path)), 'bytes': f.stat().st_size} for f in sorted(Path(path).rglob('*')) if f.is_file()]
    row = {'repo': repo, 'revision': rev, 'snapshot': path, 'seconds': time.time()-start, 'files': files, 'weight_hash_status': 'not_independently_hashed'}
    r['models'].append(row); (out/'setup.json').write_text(json.dumps(r, indent=2))
    print(json.dumps({k:v for k,v in row.items() if k != 'files'}), flush=True)
r['end_unix'] = time.time(); (out/'setup.json').write_text(json.dumps(r, indent=2))
