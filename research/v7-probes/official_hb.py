"""Usage: official_hb.py NAME METHOD [VERSION] [PROOFFILE]  METHOD in org|ours. Appends JSON to hb/official-hb.jsonl"""
import sys, json, time, re
from pathlib import Path
ROOT = Path('/mnt/SharedDrive/ActiveProjects/lean-refactor-pi'); sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'vendor/lean-refactor'))
from arena import engine
import importlib.util
_s=importlib.util.spec_from_file_location('hbtool', ROOT/'vendor/lean-refactor/lean_refactor/cc_agent/tools/heartbeat.py'); H=importlib.util.module_from_spec(_s); sys.modules['hbtool']=H; _s.loader.exec_module(H)
name, method = sys.argv[1:3]
row = engine.problem(name)
ver, commit = engine.measure_version(row)
if len(sys.argv) > 3 and sys.argv[3] != '-':
    ver = sys.argv[3]; commit = dict(engine.versions(row))[ver]
src = row['src']
label = 'ref'
if len(sys.argv) > 4:
    src = Path(sys.argv[4]).read_text(); label = Path(sys.argv[4]).stem
if src and not src.startswith(row['statement']) and False: pass
t = time.time(); hb = None; err = None
if method in ('org','orgd','orgt'):
    ws = engine.workspace(row, ver, commit)
    if engine.is_standalone(row):
        content = row['header'] + src + "\n"
        rel = 'ArenaScratch_hb.lean'
        hb, err = H.count_heartbeats(ws, rel, content, len(row['header']), timeout=600)
    else:
        # upstream function on the pinned file from git (workspace working tree may differ)
        import subprocess
        path = ws / row['file_path']
        content = path.read_text()
        pos = content.find(row['src'])
        content = content[:pos] + src + content[pos+len(row['src']):]
        ds = engine.declaration_head(content, pos) if method != 'org' else pos
        if method == 'orgt': content = content[:pos+len(src)] + '\n'
        hb, err = H.count_heartbeats(ws, row['file_path'], content, ds, timeout=600)
else:
    with engine.force_cold():
        r = engine.compile_version(row, src, ver, commit, measure=True)
    hb = r.get('heartbeats'); err = None if r['passed'] else (r.get('error') or r['raw_output'][-300:])
out = dict(name=name, method=method, ver=ver, label=label, hb=hb, sec=round(time.time()-t), err=(err or '')[:300], errlines=[x[-220:] for x in (err or '').splitlines() if ': error' in x][:3])
print(json.dumps(out))
open(ROOT/'runs/analysis/experiments/hb/official-hb.jsonl', 'a').write(json.dumps(out)+'\n')
