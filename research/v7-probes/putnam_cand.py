import sys,json
sys.path.insert(0,'.')
from arena import engine
name,ver=sys.argv[1:3]
row=engine.problem(name); commit=dict(engine.versions(row))[ver]
proof=[json.loads(l)['proof'] for l in open('runs/analysis/submission-v3/submission.jsonl') if json.loads(l)['name']==name][0]
r=engine.compile_version(row,proof,ver,commit,measure=True)
print(json.dumps({'name':name,'ver':ver,'hb':r.get('heartbeats'),'passed':r['passed'],'sec':r['lean'].get('seconds')}))
