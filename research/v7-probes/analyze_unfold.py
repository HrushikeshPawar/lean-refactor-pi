import json,re,sys,os
sys.path.insert(0,'.')
from arena import context
E='runs/analysis/experiments/'
rows=list(json.load(open(E+'answer_key_candidates.json')))
def load(n,m):
    f=E+f'ctx-{re.sub("[^A-Za-z0-9_.-]","_",n)}-{m}.json'
    return json.load(open(f)) if os.path.exists(f) else None
out=[];tot={'b':[], 'u':[]}
summ=[]
def packet_chars(ctx):
    # render packet pieces not available offline; approximate library section size
    known={i['name'] for i in ctx.get('source',[])}|{i['name'] for i in ctx.get('dependency',[])}
    recs=[i for i in ctx['library'] if i['name'] not in known and i.get('sig')]
    return len(context._library_section({**ctx,'library':recs}) and "\n".join(context._library_section(ctx)))
for n in rows:
    b,u=load(n,'base'),load(n,'unfold')
    if not b or not u: summ.append((n,'skipped / not run')); continue
    tb=[x['name'] for x in b['library'][:60]]; tu=[x['name'] for x in u['library'][:60]]
    rk={}
    for tag,c in(('b',b),('u',u)):
        for r in c['extra']:
            if r['kind']=='keyrank' and r['ckind']=='theorem': rk.setdefault(r['name'],{})[tag]=(r['rank'] or None)
    ov=len(set(tb)&set(tu))
    ub=[r for r in u['extra'] if r['kind']=='unfold_added']
    rb=[r for r in b['extra'] if r['kind']=='ranked_total']; ru=[r for r in u['extra'] if r['kind']=='ranked_total']
    summ.append((n,rk,ov,len(tb),(rb[0]['n'] if rb else None),(ru[0]['n'] if ru else None),ub[0]['count'] if ub else None,
        b['library_scan'][0]['pool'] if b['library_scan'] else None,u['library_scan'][0]['pool'] if u['library_scan'] else None,
        len("\n".join(context._library_section(b))),len("\n".join(context._library_section(u))), tb[:5],tu[:5]))
json.dump(summ,open(E+'unfold-summary.json','w'),indent=1)
for s in summ: print(s)
