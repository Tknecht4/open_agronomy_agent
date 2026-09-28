"""Derive bounded comparisons from retained instrumented cache receipts."""
import gzip,hashlib,json
from pathlib import Path
here=Path(__file__).resolve().parent
metadata=json.loads((here/'snapshot-file-manifests.json').read_text())
def changes(a,b,path=''):
 if type(a)!=type(b):return [path]
 if isinstance(a,dict):return sum((changes(a.get(k),b.get(k),path+'/'+str(k)) for k in sorted(set(a)|set(b))),[])
 if isinstance(a,list):
  if len(a)!=len(b):return [path+'/length']
  return sum((changes(x,y,path+'/'+str(i)) for i,(x,y) in enumerate(zip(a,b))),[])
 return [] if a==b else [path]
results=[]
for model in ('gemma','qwen'):
 eos=next(m['eos_token_ids'] for m in metadata if (model=='gemma')==('gemma' in m['repo']))
 for arm in ('active','method_candidate'):
  path=here/f'cache-{model}-{arm}.json.gz'
  with gzip.open(path,'rt') as f:r=json.load(f)
  c=r['conditions'];pairs=[]
  for left,right in [('off','off_repeat'),('off','split_direct'),('off','lru_cold'),('split_direct','split_manual'),('split_direct','split_clone'),('split_clone','lru_cold'),('lru_cold','lru_warm')]:
   a,b=c[left],c[right];first=next((i for i,(x,y) in enumerate(zip(a['tokens'],b['tokens'])) if x!=y),None)
   eos_a=next((i for i,x in enumerate(a['tokens']) if x in eos),None);eos_b=next((i for i,x in enumerate(b['tokens']) if x in eos),None)
   pairs.append({'left':left,'right':right,'first_divergent_token_index':first,'left_first_eos_index':eos_a,'right_first_eos_index':eos_b,'difference_before_either_eos':first is not None and all(stop is None or first<stop for stop in (eos_a,eos_b)),'prefix_state_changed_paths':changes(a['prefix_state'],b['prefix_state']) if a['prefix_state'] is not None and b['prefix_state'] is not None else None,'full_prompt_state_changed_paths':changes(a['full_prompt_state'],b['full_prompt_state'])})
  results.append({'model':model,'arm':arm,'raw_gzip_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'model_revision':r['model_revision'],'device':r['device'],'eos_token_ids':eos,'prompt_token_count':len(r['prompt_token_ids']),'prefix_token_count':len(r['prefix_token_ids']),'all_saved_prefix_unchanged':all(c[n]['saved_prefix_unchanged'] for n in ('lru_cold','lru_warm')),'clone_prefix_equals_fetched':c['split_clone']['prefix_state']==c['split_clone']['fetched_state'],'cold_prefix_equals_fetched':c['lru_cold']['prefix_state']==c['lru_cold']['fetched_state'],'cold_warm_fetched_equal':c['lru_cold']['fetched_state']==c['lru_warm']['fetched_state'],'pairs':pairs})
out={'schema':'instrumented_cache_analysis.v1','claim_eligible':False,'boundary':'Fixed320token horizon; state hashes do not prove numeric correctness; timings are not performance evidence','cases':results}
(here/'cache-analysis.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps([{'model':r['model'],'arm':r['arm'],'pairs':[{k:p[k] for k in ('left','right','first_divergent_token_index','difference_before_either_eos')} for p in r['pairs']]} for r in results],indent=2))
