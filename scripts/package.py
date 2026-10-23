#!/usr/bin/env python3
"""Build source/tools-only ZIP using an allowlist; never include work/."""
import hashlib,json,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
VERSION='0.1.0'
allowed={'README.md','LICENSE','NOTICE.md','requirements.txt','.gitignore','xiaodu.py','启动说明.txt','validation.json'}
folders={'xdtool','docs','assets','profiles','tests','scripts','.github'}
files=[]
for p in sorted(ROOT.rglob('*')):
    rel=p.relative_to(ROOT)
    if not p.is_file() or '__pycache__' in rel.parts:continue
    if len(rel.parts)==1 and rel.name not in allowed:continue
    if len(rel.parts)>1 and rel.parts[0] not in folders:continue
    if p.suffix in ('.img','.ko','.apk','.pub','.pyc'):raise RuntimeError('禁止进入公开包：'+str(rel))
    files.append((p,rel))
out=ROOT/'dist';out.mkdir(exist_ok=True)
archive=out/f'xiaodu-smart-screen-1s-root-v{VERSION}.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
    for p,rel in files:
        info=zipfile.ZipInfo(f'xiaodu-smart-screen-1s-root-v{VERSION}/'+rel.as_posix(),(2026,10,23,0,0,0))
        info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=(0o755 if p.suffix=='.sh' else 0o644)<<16
        z.writestr(info,p.read_bytes())
digest=hashlib.sha256(archive.read_bytes()).hexdigest()
(out/(archive.name+'.sha256')).write_text(digest+'  '+archive.name+'\n')
print(json.dumps({'archive':str(archive),'sha256':digest,'files':len(files),'bytes':archive.stat().st_size},ensure_ascii=False,indent=2))
