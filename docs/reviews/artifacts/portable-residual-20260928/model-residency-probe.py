"""Model-free process-isolated probe of model residency, not memory measurement."""
import hashlib,json,subprocess
from pathlib import Path
from agronomy_agent import agent
assert not agent._MLX_MODEL_CACHE
calls=[]
def fake_load(name,**kwargs):
    calls.append(name)
    return object(),object()
observations=[]
for name in ('fixture-a','fixture-b','fixture-c','fixture-a'):
    agent.MLXGenerator._load_cached(fake_load,name,revision='fixture-r1')
    observations.append({'request':name,'resident_keys':sorted(agent._MLX_MODEL_CACHE),'load_calls':len(calls)})
agent.reset_mlx_prompt_caches()
root=Path(__file__).resolve().parents[4]
source=root/'src/agronomy_agent/agent.py'
out={'schema':'model_residency_source_probe.v1','status':'model_free_exploratory','source_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'observations':observations,'after_prompt_cache_reset_resident_keys':sorted(agent._MLX_MODEL_CACHE),'interpretation':'Distinct model cache keys remain resident without automatic capacity eviction; prompt cache reset does not unload weights. This probe used plain Python objects and measured no model memory or OOM.'}
Path(__file__).with_name('model-residency-results.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps(out,indent=2))
