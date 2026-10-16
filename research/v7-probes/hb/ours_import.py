import sys, json, importlib.util
from pathlib import Path
ROOT=Path('/mnt/SharedDrive/ActiveProjects/lean-refactor-pi'); sys.path.insert(0,str(ROOT))
from arena import engine
_s=importlib.util.spec_from_file_location('hbtool', ROOT/'vendor/lean-refactor/lean_refactor/cc_agent/tools/heartbeat.py'); H=importlib.util.module_from_spec(_s); sys.modules['hbtool']=H; _s.loader.exec_module(H)
orig=engine.run_lean
def patched(row, project, text, **kw): return orig(row, project, H.ensure_count_heartbeats_import(text), **kw)
engine.run_lean=patched
row=engine.problem(sys.argv[1]); v,c=engine.measure_version(row)
with engine.force_cold(): r=engine.compile_version(row,row['src'],v,c,measure=True)
print(json.dumps({'name':sys.argv[1],'ours+import':r.get('heartbeats'),'passed':r['passed']}))
