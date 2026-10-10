import sys,json,time
sys.path.insert(0,'.')
from arena import engine
from arena.engine import problem,versions,candidate_file,run_lean,lean_timeout,last_lean_run
import re
name,ver,mode=sys.argv[1:4]
row=problem(name)
commit=dict(versions(row))[ver]
built=candidate_file(row,row['src'],ver,commit)
text=built['text']
if mode=='wrapper':
    r=engine.compile_version(row,row['src'],ver,commit,measure=True)
    print(json.dumps({'name':name,'ver':ver,'mode':mode,'hb':r.get('heartbeats'),'passed':r['passed'],'sec':r['lean'].get('seconds'),'err':r.get('error')}))
else:
    # count_heartbeats variant
    text=text[:built['head']]+'set_option Elab.async false in\n#count_heartbeats in\n'+text[built['head']:]
    with engine.force_cold():
        t=time.time()
        out=run_lean(row,built['path'],text,timeout=600,prefix_end=built['head'])
    rc,o=out if out else (None,'TIMEOUT')
    m=re.findall(r'([^\n]*heartbeats[^\n]*)',o)
    print(json.dumps({'name':name,'ver':ver,'mode':mode,'rc':rc,'match':m,'sec':round(time.time()-t),'err':[x for x in o.splitlines() if 'error' in x or 'heartbeat' in x.lower()][:5]}))
