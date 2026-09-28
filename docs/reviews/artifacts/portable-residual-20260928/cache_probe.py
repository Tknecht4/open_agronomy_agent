#!/usr/bin/env python3
"""Non-claim cache investigation. Default is source-only; real execution is opt-in.

No downloads. --execute requires an existing revision-named local HF snapshot.
Instrumented timings are not benchmarks. Run each model/cell into a new output
directory. Fixed token horizon includes EOS for causal comparison, unlike the
product's stop-at-EOS stream. Only pre-first-divergence logits are causal pairs.
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import copy
import functools
import gzip
import hashlib
import importlib.metadata as metadata
import json
import os
import platform
import sys
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def partitions(n, step):
    result = []
    while n > 1:
        count = min(step, n - 1)
        result.append(count)
        n -= count
    return result + [n]


def probes(path):
    with gzip.open(path, "rt") as stream:
        for line in stream:
            row = json.loads(line)
            for turn in row.get("turns", []):
                if "direct_cache_probe" in turn:
                    yield row["unit_id"], turn["direct_cache_probe"]


def inspect_ledger(path):
    out = []
    for unit, probe in probes(path):
        outputs = {x["condition"]: x for x in probe["outputs"]}
        stats = outputs["cold"]["generation_stats"]
        n, prefix, step = (stats[k] for k in ("prompt_tokens", "cached_prompt_tokens", "prefill_step_size"))
        a, b = outputs["disabled"]["answer"], outputs["cold"]["answer"]
        char = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
        out.append({"unit": unit, "prompt_sha256": probe["prompt_sha256"],
                    "tokens": n, "prefix_tokens": prefix, "prefill_step_size": step,
                    "off_partitions": partitions(n, step),
                    "on_partitions": partitions(prefix, step) + partitions(n-prefix, step),
                    "disabled_equals_cold": a == b,
                    "cold_equals_warm": b == outputs["warm"]["answer"],
                    "first_different_character": char,
                    "disabled_excerpt": a[max(0,char-35):char+70],
                    "cold_excerpt": b[max(0,char-35):char+70],
                    "seed_application": stats["seed_application"],
                    "kv_bits": stats["kv_bits"], "max_kv_size": stats["max_kv_size"]})
    return out


def source_self_test():
    """Execute installed generate_step/LRU AST with NumPy fake model; no MLX import."""
    import numpy as np
    root = Path(metadata.distribution("mlx-lm").locate_file("mlx_lm"))
    source = (root / "generate.py").read_text()
    node = next(x for x in ast.parse(source).body if isinstance(x, ast.FunctionDef) and x.name == "generate_step")
    class State:
        def __init__(self): self.tokens = []
        @property
        def state(self): return self.tokens
        @property
        def nbytes(self): return len(self.tokens)*4
    class Model:
        def __call__(self, tokens, cache):
            cache[0].tokens.extend(tokens[0].tolist())
            return np.array([[[0., float(sum(cache[0].tokens)), -1.]]])
    mx = SimpleNamespace(stream=lambda _: contextlib.nullcontext(),
                         argmax=np.argmax, concat=np.concatenate,
                         logsumexp=lambda x, keepdims: np.log(np.exp(x).sum(keepdims=keepdims)),
                         eval=lambda *a: None, async_eval=lambda *a: None, clear_cache=lambda: None)
    env = dict(mx=mx, generation_stream=None, functools=functools,
               maybe_quantize_kv_cache=lambda *a, **kw: None,
               cache=SimpleNamespace(make_prompt_cache=lambda *a, **kw: [State()]))
    exec(compile("from __future__ import annotations\n"+ast.unparse(node), "installed-generate-step", "exec"), env)
    generate = env["generate_step"]
    cache_source = (root / "models/cache.py").read_text()
    classes = [x for x in ast.parse(cache_source).body if isinstance(x, ast.ClassDef) and x.name in {"PromptTrieResult", "PromptTrie", "LRUPromptCache"}]
    env.update(dataclass=dataclass, copy=copy, deque=deque, can_trim_prompt_cache=lambda _:False,
               Any=Any, List=list)
    exec(compile("from __future__ import annotations\n"+"\n".join(ast.unparse(x) for x in classes), "installed-lru", "exec"), env)
    prefix, suffix = [1,2,3,4,5], [6,7,8]
    state = [State()]
    yielded = list(generate(np.array(prefix), Model(), max_tokens=0, prompt_cache=state, prefill_step_size=3))
    assert yielded == [] and state[0].tokens == prefix
    lru = env["LRUPromptCache"]()
    lru.insert_cache("fake", prefix, state, cache_type="system")
    fetched, rest = lru.fetch_nearest_cache("fake", prefix+suffix)
    assert rest == suffix and fetched[0].tokens == prefix
    fetched[0].tokens.append(99)
    again, _ = lru.fetch_nearest_cache("fake", prefix+suffix)
    assert again[0].tokens == prefix
    return {"status":"passed", "no_mlx_import": "mlx.core" not in sys.modules,
            "max_tokens_zero_consumed_exact_prefix":True, "max_tokens_zero_yielded":len(yielded),
            "lru_copy_isolation_fake_state":True,
            "generate_source_sha256":digest(source.encode()), "cache_source_sha256":digest(cache_source.encode()),
            "limit":"NumPy fake model validates source control flow, not numerical MLX/model cache behavior"}


def execute(args, probe, out):
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    snapshot = Path(args.snapshot).resolve()
    outputs = {x["condition"]: x for x in probe["outputs"]}
    historical = outputs["cold"]
    stats = historical["generation_stats"]
    revision = historical["model_identity"]["configured_model_revision"]
    if not snapshot.is_dir() or snapshot.name != revision:
        raise ValueError("snapshot must be an existing local directory named with retained model revision")
    if stats["kv_bits"] is not None or stats["max_kv_size"] is not None:
        raise ValueError("this narrow probe supports retained unquantized/unbounded KV settings only")
    import mlx.core as mx
    import numpy as np
    from mlx_lm import load
    from mlx_lm.generate import generate_step, generation_stream
    from mlx_lm.models.cache import make_prompt_cache, LRUPromptCache
    from mlx_lm.sample_utils import make_sampler
    model, tokenizer = load(str(snapshot))
    messages = probe["prompt_messages"]
    tokens = list(tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True, enable_thinking=False))
    if len(tokens) != stats["prompt_tokens"]:
        raise ValueError("retained prompt length does not match; tokenizer/template identity requires investigation")
    prefix = stats["cached_prompt_tokens"]
    step = stats["prefill_step_size"]
    seed = stats["seed_application"]["applied_seed"]
    settings = stats["seed_application"]["sampler"]
    if settings["temperature"] != 0:
        raise ValueError("probe scoped to retained argmax cells")
    out.update(prompt_messages=messages, prompt_token_ids=tokens, prefix_token_ids=tokens[:prefix],
               prompt_token_ids_sha256=digest(canonical(tokens)), snapshot=str(snapshot),
               model_revision=revision, device=str(mx.default_device()),
               settings={"seed":seed,"temperature":0,"top_p":settings["top_p"],"top_k":settings["top_k"],
                         "prefill_step_size":step,"max_tokens":args.max_tokens,"kv_bits":None,"max_kv_size":None},
               snapshot_small_file_sha256={p.name:digest(p.read_bytes()) for p in snapshot.iterdir()
                                          if p.is_file() and p.suffix in {".json", ".jinja"} and p.stat().st_size < 30000000})
    def flat_state(value, name=""):
        if isinstance(value, dict):
            return sum((flat_state(v, f"{name}/{k}") for k,v in sorted(value.items())), [])
        if isinstance(value, (tuple,list)):
            return sum((flat_state(v, f"{name}/{i}") for i,v in enumerate(value)), [])
        if isinstance(value, mx.array):
            mx.eval(value)
            # float32 represents every bf16 value exactly; dtype separately retained.
            arr = np.asarray(value.astype(mx.float32) if value.dtype==mx.bfloat16 else value)
            return [{"path":name,"shape":list(value.shape),"dtype":str(value.dtype),"sha256":digest(arr.tobytes())}]
        return [{"path":name,"scalar":str(value)}]
    def state_receipt(cache):
        result=[]
        for c in cache:
            item={"class":type(c).__name__, "offset":str(getattr(c,"offset",None)),
                  "meta_state":str(getattr(c,"meta_state",None)),"state":flat_state(c.state),
                  "left_padding":flat_state(getattr(c,"left_padding",None)),
                  "lengths":flat_state(getattr(c,"lengths",None))}
            if type(c).__name__=="RotatingKVCache":
                item["temporal_state"]=flat_state((c._temporal_order(c.keys),c._temporal_order(c.values)))
            result.append(item)
        return result
    def offsets(cache):
        return [str(getattr(c,"offset",None)) for c in cache]
    class TraceModel:
        def __init__(self): self.calls=[]; self.consumed=0; self.logits=[]; self.full_state=None
        def __getattr__(self, name): return getattr(model,name)
        def __call__(self, ids, cache):
            before=offsets(cache); result=model(ids,cache=cache); n=int(ids.shape[1]); self.consumed+=n
            self.calls.append({"n":n,"before":before,"after":offsets(cache),"consumed":self.consumed})
            if self.consumed >= len(tokens):
                self.logits.append(np.asarray(result[0,-1,:].astype(mx.float32)))
                if self.full_state is None: self.full_state=state_receipt(cache)
            return result
    saved_lru = None
    results = {}
    vectors = {}
    for condition in ("off", "off_repeat", "split_direct", "split_manual", "split_clone", "lru_cold", "lru_warm"):
        mx.random.seed(seed)
        trace=TraceModel(); cache=make_prompt_cache(model); prompt=tokens
        prefix_state=None; fetched_state=None; saved_before=None
        if condition not in {"off", "off_repeat"}:
            if condition=="lru_warm":
                cache,prompt=saved_lru.fetch_nearest_cache("probe",tokens)
                trace.consumed=prefix
                fetched_state=state_receipt(cache)
            else:
                if condition=="split_manual":
                    pos=0
                    with mx.stream(generation_stream):
                        for count in partitions(prefix,step):
                            trace(mx.array(tokens[pos:pos+count])[None],cache=cache)
                            mx.eval([c.state for c in cache]); mx.clear_cache(); pos+=count
                else:
                    list(generate_step(mx.array(tokens[:prefix]),trace,max_tokens=0,prompt_cache=cache,
                                       prefill_step_size=step,sampler=lambda x:mx.argmax(x,axis=-1)))
                prefix_state=state_receipt(cache)
                prompt=tokens[prefix:]
                if condition=="split_clone":
                    cache=copy.deepcopy(cache)
                    fetched_state=state_receipt(cache)
                if condition=="lru_cold":
                    saved_lru=LRUPromptCache()
                    saved_lru.insert_cache("probe", tokens[:prefix],cache,cache_type="system")
                    cache,prompt=saved_lru.fetch_nearest_cache("probe",tokens)
                    fetched_state=state_receipt(cache)
            if condition.startswith("lru_"):
                ref,_=saved_lru.fetch_nearest_cache("probe",tokens)
                saved_before=state_receipt(ref); del ref
        generated=[]; top=[]
        for token, logprobs in generate_step(mx.array(prompt),trace,max_tokens=args.max_tokens,prompt_cache=cache,
                                            prefill_step_size=step,sampler=make_sampler(temp=0,top_p=settings["top_p"],top_k=settings["top_k"])):
            generated.append(token)
            raw=trace.logits[len(generated)-1]
            ix=np.argsort(raw)[-10:][::-1]
            top.append({"token":token,"top_token_ids":ix.tolist(),"raw_logits":raw[ix].tolist(),
                        "top_two_margin":float(raw[ix[0]]-raw[ix[1]])})
        saved_after=None
        if condition.startswith("lru_"):
            ref,_=saved_lru.fetch_nearest_cache("probe",tokens)
            saved_after=state_receipt(ref); del ref
        results[condition]={"tokens":generated,"text":tokenizer.decode(generated),"top_logits":top,
                            "calls":trace.calls,"prefix_state":prefix_state,"fetched_state":fetched_state,
                            "full_prompt_state":trace.full_state,
                            "saved_prefix_unchanged":saved_before==saved_after if saved_before else None}
        vectors[condition]=trace.logits[:len(generated)]
        out["conditions"]=results
        (Path(args.output)/"cache-runtime.json").write_text(json.dumps(out,indent=2))
        del cache,trace
        mx.clear_cache()
    comparisons=[]
    for left,right in (("off","off_repeat"),("off","split_direct"),("split_direct","split_manual"),
                       ("split_direct","split_clone"),("split_clone","lru_cold"),
                       ("split_direct","lru_cold"),("lru_cold","lru_warm")):
        a,b=results[left]["tokens"],results[right]["tokens"]
        first=next((i for i,(x,y) in enumerate(zip(a,b)) if x!=y),None)
        stop=(first+1) if first is not None else len(a)
        differences=[float(np.max(np.abs(vectors[left][i]-vectors[right][i]))) for i in range(stop)]
        comparisons.append({"left":left,"right":right,"first_divergent_token_index":first,
                            "tokens_equal_within_horizon":a==b,"max_abs_logit_difference_on_common_history":differences,
                            "full_prompt_state_exact_equal":results[left]["full_prompt_state"]==results[right]["full_prompt_state"]})
        if first is not None:
            np.savez_compressed(Path(args.output)/f"{left}-vs-{right}-first-divergence.npz",
                                left=vectors[left][first],right=vectors[right][first])
    out["comparisons"]=comparisons
    (Path(args.output)/"cache-runtime.json").write_text(json.dumps(out,indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger",type=Path,required=True)
    parser.add_argument("--unit",default="cache/active/PFMH3-01")
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--self-test",action="store_true")
    parser.add_argument("--execute",action="store_true")
    parser.add_argument("--snapshot")
    parser.add_argument("--max-tokens",type=int,default=64)
    args=parser.parse_args()
    if not 1<=args.max_tokens<=320: parser.error("--max-tokens must be 1..320")
    if args.execute and not args.snapshot: parser.error("--execute requires --snapshot")
    args.output.mkdir(parents=True,exist_ok=False)
    out={"schema":"cache_cause_probe.v1","claim_eligible":False,"platform":platform.platform(),
         "python":sys.version,"packages":{n:metadata.version(n) for n in ("mlx","mlx-lm")},
         "script_sha256":digest(Path(__file__).read_bytes()),"ledger_sha256":digest(args.ledger.read_bytes()),
         "ledger":str(args.ledger.resolve()),"inspection":inspect_ledger(args.ledger),
         "real_runtime_executed":False}
    root=Path(metadata.distribution("mlx-lm").locate_file("mlx_lm"))
    out["installed_source_sha256"]={name:digest((root/name).read_bytes()) for name in
                                  ("generate.py","sample_utils.py","models/cache.py","models/qwen3_5.py","models/gemma4_text.py","models/gated_delta.py")}
    if args.self_test: out["source_control_flow_self_test"]=source_self_test()
    (args.output/"cache-source.json").write_text(json.dumps(out,indent=2))
    if args.execute:
        if out["packages"]!={"mlx":"0.32.2","mlx-lm":"0.31.3"}:
            raise ValueError("exact historical package versions required")
        probe=dict(probes(args.ledger))[args.unit]
        out["real_runtime_executed"]=True
        execute(args,probe,out)
    print(json.dumps({"output":str(args.output),"real_runtime_executed":args.execute,"self_test":out.get("source_control_flow_self_test",{}).get("status")}))


if __name__=="__main__": main()
