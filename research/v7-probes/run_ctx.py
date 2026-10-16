import sys,json,time,re
sys.path.insert(0,'.')
from arena import engine, context
from arena.engine import problem,measure_version,candidate_file,run_lean,is_standalone
name,mode=sys.argv[1:3]
row=problem(name); version,commit=measure_version(row)
E='runs/analysis/experiments/'
src=open(E+'context_unfold.lean').read()
keys=json.load(open(E+'answer_key_candidates.json'))[name]
roots="" if is_standalone(row) else ", ".join(json.dumps(p) for p in sorted({row["file_path"].split("/")[0]}))
inserted=(src.replace("@@ROOTS@@",roots).replace("@@TARGET@@",context._lean_name(name))
   .replace("@@UNFOLD@@","true" if mode=='unfold' else "false").replace("@@KEY@@",", ".join(json.dumps(k) for k in keys)))
built=candidate_file(row,row["src"],version,commit)
text=built["text"][:built["head"]]+inserted+built["text"][built["head"]:]
t=time.time()
with engine.force_cold():
    ran=run_lean(row,built["path"],text,timeout=600,prefix_end=built["head"])
sec=round(time.time()-t,1)
if ran is None:
    print(json.dumps({'name':name,'mode':mode,'timeout':True,'sec':sec})); sys.exit()
rc,out=ran
open(E+f'ctx-raw-{re.sub("[^A-Za-z0-9_.-]","_",name)}-{mode}.txt','w').write(out)
parsed=context.parse_context(out,inserted.count("\n"),built["start_line"],context._proof_boundary(row["src"],1))
extra=[json.loads(x) for x in re.findall(r"^ARENA_CTX (\{.*\})$",out,re.M)]
extra=[r for r in extra if r['kind'] in('keyrank','libraryrank','ranked_total','unfold_added')]
parsed['extra']=extra
json.dump(parsed,open(E+f'ctx-{re.sub("[^A-Za-z0-9_.-]","_",name)}-{mode}.json','w'))
print(json.dumps({'name':name,'mode':mode,'sec':sec,'complete':parsed['complete'],'lib':len(parsed['library']),'scan':parsed['library_scan'],'extra':len(extra),'fail':[f.get('message','')[:150] for f in parsed['failure']][:2]}))
