#!/usr/bin/env python3
"""Compile explicit Allegro package specifications and verify native DRA/PSM readback."""
import copy
import argparse
from collections import Counter
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

LAYERS = {'PACKAGE GEOMETRY/ASSEMBLY_TOP', 'PACKAGE GEOMETRY/SILKSCREEN_TOP'}
TEXT_LAYERS = LAYERS | {'REF DES/ASSEMBLY_TOP', 'REF DES/SILKSCREEN_TOP'}
BOUND = 'PACKAGE GEOMETRY/PLACE_BOUND_TOP'


def keys(o, required, optional=()):
    if not isinstance(o, dict) or set(o)-set(required)-set(optional) or set(required)-set(o):
        raise ValueError(f'Expected fields {required}; optional {optional}')


def num(v, accuracy=None, positive=False):
    if isinstance(v, bool) or not isinstance(v, (str, int, float)):
        raise ValueError('Expected explicit numeric dimension')
    try: d = Decimal(str(v))
    except InvalidOperation: raise ValueError('Invalid dimension')
    if not d.is_finite() or abs(d) > 10000 or (positive and d <= 0):
        raise ValueError('Dimension outside supported range')
    if accuracy is not None and d != d.quantize(Decimal(1).scaleb(-accuracy)):
        raise ValueError('Dimension loses precision at requested accuracy')
    return float(d)


def point(v, acc):
    if not isinstance(v, list) or len(v) != 2: raise ValueError('Point must be [x,y]')
    return [num(x, acc) for x in v]


def normalize_measurement(spec):
    """Centre on the physical body, not the pin centroid or text extents."""
    s=copy.deepcopy(spec);m=s.pop('measurement',None)
    if m is None:return s,None
    keys(m,['basis'],['body_bounds','pad_origin_shifts'])
    if not isinstance(m['basis'],str) or not m['basis'].strip():raise ValueError('Measurement basis required')
    a=s['accuracy']
    if 'body_bounds' in m:
        b=m['body_bounds'];keys(b,['min','max']);lo=point(b['min'],a);hi=point(b['max'],a)
    else:
        pts=[point(p,a) for o in s['outlines'] if o['layer']=='PACKAGE GEOMETRY/ASSEMBLY_TOP' for p in o['points']]
        if not pts:raise ValueError('Body bounds or assembly outline required for centering')
        lo=[min(p[i] for p in pts) for i in (0,1)];hi=[max(p[i] for p in pts) for i in (0,1)]
    if any(x>=y for x,y in zip(lo,hi)):raise ValueError('Invalid body bounds')
    c=[(x+y)/2 for x,y in zip(lo,hi)]
    def shifted(p):return [num(round(x-y,10),a) for x,y in zip(point(p,a),c)]
    shifts=m.get('pad_origin_shifts',{})
    if not isinstance(shifts,dict) or not set(shifts)<=set(s['padstacks']):raise ValueError('Unknown pad origin shift')
    pin_changes=[]
    for pin in s['pins']:
        old=point(pin['xy'],a);dx,dy=point(shifts.get(pin['padstack'],[0,0]),a)
        rotations={0:(dx,dy),90:(-dy,dx),180:(-dx,-dy),270:(dy,-dx)}
        if pin['rotation'] not in rotations:raise ValueError('Orthogonal pin rotation required')
        rx,ry=rotations[pin['rotation']]
        pin['xy']=shifted([round(old[0]+rx,10),round(old[1]+ry,10)])
        pin_changes.append({'number':pin['number'],'source':old,'centered':pin['xy']})
    for o in s['outlines']:o['points']=[shifted(p) for p in o['points']]
    for t in s['texts']:t['xy']=shifted(t['xy'])
    for k in ('min','max'):s['place_bound'][k]=shifted(s['place_bound'][k])
    record={'definition':'body_bbox_center','source_center':c,'translation':[-x for x in c],
            'units':s['units'],'basis':m['basis'],'pins':pin_changes,'pad_origin_shifts':shifts}
    s['sources'].append({'location':'coordinate normalization','basis':json.dumps(record,ensure_ascii=False)})
    return s,record


def validate(s):
    keys(s, ['schema','name','units','accuracy','sources','padstacks','pins','outlines','place_bound','texts','text_style','silk_clearance'])
    if type(s['schema']) is not int or s['schema'] != 1: raise ValueError('schema must be 1')
    if not isinstance(s['name'], str) or not re.fullmatch('[a-z][a-z0-9_]{0,30}',s['name']): raise ValueError('Invalid package name')
    a=s['accuracy']
    if type(a) is not int or s['units'] not in ('mm','mil') or not (2 if s['units']=='mm' else 0) <= a <= 4: raise ValueError('Invalid units/accuracy')
    if not isinstance(s['sources'],list) or not s['sources']: raise ValueError('Sources required')
    for v in s['sources']:
        keys(v,['location','basis'],['path'])
        if any(not isinstance(x,str) or not x.strip() for x in v.values()): raise ValueError('Source fields must be nonempty strings')
    if not isinstance(s['padstacks'],dict) or not s['padstacks']: raise ValueError('Explicit padstacks required')
    for k,v in s['padstacks'].items():
        if not re.fullmatch('[a-z][a-z0-9_]{0,30}',k) or not isinstance(v,str) or not Path(v).is_absolute() or Path(v).suffix.lower()!='.pad': raise ValueError('Padstacks map names to absolute PAD file paths')
    if not isinstance(s['pins'],list) or not 1 <= len(s['pins']) <= 1000: raise ValueError('Expected 1..1000 pins')
    ids=set(); positions=set()
    for p in s['pins']:
        keys(p,['number','padstack','xy','rotation'])
        if not isinstance(p['number'],str) or not re.fullmatch('[A-Za-z0-9_]{1,16}',p['number']) or p['number'].upper() in ids: raise ValueError('Invalid/duplicate pin number')
        ids.add(p['number'].upper())
        if p['padstack'] not in s['padstacks']: raise ValueError('Unknown padstack reference')
        xy=tuple(point(p['xy'],a))
        if xy in positions: raise ValueError('Coincident pins unsupported')
        positions.add(xy)
        if num(p['rotation']) not in (0,90,180,270): raise ValueError('First version supports orthogonal pin rotations')
    if {p['padstack'] for p in s['pins']} != set(s['padstacks']): raise ValueError('Unused padstack reference')
    if not isinstance(s['outlines'],list) or not s['outlines']: raise ValueError('Outlines required')
    for o in s['outlines']:
        keys(o,['layer','width','points'])
        if o['layer'] not in LAYERS: raise ValueError('Unsupported outline layer')
        num(o['width'],a,True)
        if not isinstance(o['points'],list) or not 2 <= len(o['points']) <= 1000: raise ValueError('Polyline needs 2..1000 points')
        pts=[point(p,a) for p in o['points']]
        if any(x==y for x,y in zip(pts,pts[1:])): raise ValueError('Zero length segment')
    if not any(o['layer']=='PACKAGE GEOMETRY/ASSEMBLY_TOP' for o in s['outlines']): raise ValueError('Assembly outline required')
    b=s['place_bound'];keys(b,['min','max','height'])
    lo,hi=point(b['min'],a),point(b['max'],a)
    if any(x>=y for x,y in zip(lo,hi)): raise ValueError('Invalid place bound')
    num(b['height'],a,True)
    for p in s['pins']:
        if not all(x<=v<=y for x,v,y in zip(lo,point(p['xy'],a),hi)): raise ValueError('Pin outside place bound')
    tstyle=s['text_style'];keys(tstyle,['width','height','line_space','char_space','stroke'])
    for k,v in tstyle.items():
        n=num(v,a,k not in ('char_space','line_space'))
        if n<0: raise ValueError('Negative text spacing')
    if not isinstance(s['texts'],list) or not s['texts']: raise ValueError('Refdes text required')
    refdes=[]
    for t in s['texts']:
        keys(t,['layer','text','xy','rotation'])
        if t['layer'] not in TEXT_LAYERS or not isinstance(t['text'],str) or not re.fullmatch('[A-Za-z0-9_*.+ -]{1,40}',t['text']): raise ValueError('Invalid text/layer')
        point(t['xy'],a)
        if num(t['rotation']) not in (0,90,180,270): raise ValueError('Unsupported text rotation')
        if t['layer'].startswith('REF DES/'):
            if not re.fullmatch(r'[A-Z]+\*',t['text']): raise ValueError('Refdes must be a prefix and one wildcard, e.g. U*')
            refdes.append(t['text'])
    if not refdes or len(set(refdes))!=1: raise ValueError('Consistent reference designator required')
    if num(s['silk_clearance'],a)<0: raise ValueError('Negative clearance')
    return s


def q(s): return json.dumps(s,ensure_ascii=True)
def pt(p): return f'list({num(p[0]):.6f} {num(p[1]):.6f})'
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def generate(s):
    style=s['text_style'];b=s['place_bound']
    code=['; Generated from reviewed package specification.',
          'procedure(pkgBuild() let((tb r f)',
          f'unless(axlDBChangeDesignUnits({q("millimeters" if s["units"]=="mm" else "mils")} {s["accuracy"]}) error("Units failed"))',
          'unless(axlDBChangeDesignExtents(list(-10000:-10000 10000:10000)) error("Extents failed"))',
          'axlSetVariable("padpath" ".")',
          'tb=axlDBTextBlockCreate(1 '+ ' '.join(f'?{k} {num(style[v]):.6f}' for k,v in [('width','width'),('height','height'),('lineSpace','line_space'),('charSpace','char_space'),('photoWidth','stroke')])+')',
          'unless(tb error("Text block failed"))']
    for p in s['pins']:
        code.append(f'unless(axlDBCreatePin({q(p["padstack"])} {pt(p["xy"])} make_axlPinText(?number {q(p["number"])} ?offset 0:0 ?text sprintf(nil "%d" tb)) {num(p["rotation"]):.6f}) error("Pin failed"))')
    for o in s['outlines']:
        code.append(f'unless(axlDBCreateLine(list({" ".join(pt(p) for p in o["points"])}) {num(o["width"]):.6f} {q(o["layer"])}) error("Outline failed"))')
    code+= [f'r=axlDBCreateRectangle(list({pt(b["min"])} {pt(b["max"])}) t {q(BOUND)})',
            'unless(r error("Place bound failed"))',
            f'unless(axlDBAddProp(car(r) list(list("PACKAGE_HEIGHT_MAX" {num(b["height"]):.6f}))) error("Height property failed"))']
    for t in s['texts']:
        code.append(f'unless(axlDBCreateText({q(t["text"])} {pt(t["xy"])} make_axlTextOrientation(?textBlock sprintf(nil "%d" tb) ?rotation {num(t["rotation"]):.6f} ?mirrored nil ?justify "center") {q(t["layer"])}) error("Text failed"))')
    code += [f'unless(axlSaveDesign(?design {q(s["name"]+".dra")} ?noMru t) error("Save failed"))',
             'f=outfile("build.done") fprintf(f "done\\n") close(f)', '))', 'pkgBuild()']
    return '\n'.join(code)+'\n'


def live_editor(pid,cwd):
    d=Path('/proc')/str(pid)
    try:
        if (d/'stat').read_text().split(') ',1)[1].split()[0]=='Z':return False
        return (d/'cwd').resolve()==cwd and (d/'exe').resolve().name=='allegro.exe' and b'-nograph' in (d/'cmdline').read_bytes().split(b'\0')
    except OSError:return False


def editor_pids(cwd):
    return [int(p.name) for p in Path('/proc').iterdir() if p.name.isdigit() and live_editor(int(p.name),cwd)]


def native_run(command,cwd,env,timeout,log,cleanup=False,done=None):
    start=time.monotonic(); ended=None; cleaned=False; timed=False; native_pid=None; reclaimed=[]; forced=[]; remaining=[]
    with log.open('w') as f:
        p=subprocess.Popen(command,cwd=cwd,env=env,stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
        while p.poll() is None or (done and editor_pids(cwd)):
            now=time.monotonic();j=cwd/'allegro.jrl'
            if done and j.exists():
                text=j.read_text(errors='replace');m=re.search(r'\bPid=(\d+)',text)
                if m: native_pid=int(m[1])
                if cleanup and done and done.is_file() and 'allegro 17.2 P25 Linux SPB 64-bit Edition' in text and 'Journal end' in text and re.search(r'\\i .*\) exit\s',text): ended=ended or now
            cleaned=ended is not None and now-ended>=2
            if cleaned or now-start>=timeout:
                timed=not cleaned
                # MainWin may detach and ignore SIGTERM. Wrapper exit alone
                # is not evidence that the native process was reclaimed.
                reclaimed=editor_pids(cwd) if done else []
                for pid in reclaimed:
                    try:os.kill(pid,signal.SIGTERM)
                    except ProcessLookupError:pass
                try:os.killpg(p.pid,signal.SIGTERM)
                except ProcessLookupError:pass
                try:p.wait(timeout=3)
                except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
                until=time.monotonic()+.5
                while any(live_editor(pid,cwd) for pid in reclaimed) and time.monotonic()<until:time.sleep(.05)
                for pid in reclaimed:
                    if live_editor(pid,cwd):
                        try:os.kill(pid,signal.SIGKILL);forced.append(pid)
                        except ProcessLookupError:pass
                until=time.monotonic()+2
                while any(live_editor(pid,cwd) for pid in reclaimed) and time.monotonic()<until:time.sleep(.05)
                remaining=[pid for pid in reclaimed if live_editor(pid,cwd)]
                break
            time.sleep(.1)
    return {'command':command,'returncode':p.returncode,'timed_out':timed,'ended_session_cleanup':cleaned,'native_pid':native_pid,'reclaimed_native_pids':reclaimed,'sigkill_native_pids':forced,'remaining_native_pids':remaining,'seconds':round(time.monotonic()-start,2)}


def normalize_records(s,path):
    rows=[line.split('|') for line in path.read_text(encoding='utf-8').splitlines()]
    if not rows or rows[-1]!=['END']:raise ValueError('Incomplete native readback')
    units='millimeters' if s['units']=='mm' else 'mils'
    if rows[0]!=['UNITS',units,str(s['accuracy'])]:raise ValueError('Units or accuracy mismatch')
    lengths={'TYPE':2,'PIN':12,'LINE':7,'RECT':6,'TEXT':8,'FONT':6,'HEIGHT':2,'TEXTBOX':6}
    for row in rows[1:-1]:
        if row[0] not in lengths or len(row)!=lengths[row[0]]:
            raise ValueError(f'Malformed or unsupported native record: {row}')
    return rows


def rounded(v):
    value=float(v)
    if not math.isfinite(value):raise ValueError('Non-finite native geometry')
    return round(value,6)


def readback_box(values):
    box=list(map(float,values))
    if len(box)!=4 or not all(math.isfinite(v) for v in box) or box[0]>box[2] or box[1]>box[3]:
        raise ValueError('Invalid native bounding box')
    return box


def segment(layer,width,p1,p2):return (layer,rounded(width),tuple(sorted((tuple(map(rounded,p1)),tuple(map(rounded,p2))))))


def segment_box_distance(a,b,box):
    # Liang-Barsky intersection plus exact point/edge distance.
    lo,hi=0.0,1.0
    for i in (0,1):
        delta=b[i]-a[i]
        if abs(delta)<1e-12:
            if not box[i]<=a[i]<=box[i+2]:lo=2.0;break
        else:
            u,v=sorted(((box[i]-a[i])/delta,(box[i+2]-a[i])/delta))
            lo=max(lo,u);hi=min(hi,v)
    if lo<=hi:return 0.0
    def pseg(p):
        dx,dy=b[0]-a[0],b[1]-a[1];den=dx*dx+dy*dy
        t=max(0,min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/den)) if den else 0
        return math.hypot(p[0]-a[0]-t*dx,p[1]-a[1]-t*dy)
    def pbox(p):return math.hypot(max(box[0]-p[0],p[0]-box[2],0),max(box[1]-p[1],p[1]-box[3],0))
    return min(pbox(a),pbox(b),*(pseg((x,y)) for x in (box[0],box[2]) for y in (box[1],box[3])))


def pad_signature(path):
    lines=path.read_text(errors='replace').splitlines()
    units=next(x for x in lines if x.startswith('Dimensions in '))
    kind=next(x.split(' Type: ',1)[1] for x in lines if x.startswith('Padstack: '))
    start=next(i for i,x in enumerate(lines) if x.startswith('Layer,Pad Type,'))
    return [units,kind]+[x.strip() for x in lines[start:] if x.strip() and not x.startswith('Drill Data for ')]


def verify(s,path):
    rows=normalize_records(s,path)
    if sum(r[0]=='TYPE' for r in rows)!=1:raise ValueError('Missing or duplicate symbol type')
    pins={};lines=[];rect=[];texts=[];fonts=[];heights=[];textboxes=[]
    for r in rows[1:-1]:
        if r[0]=='TYPE':
            if r[1].upper()!='PACKAGE':raise ValueError('Not a package symbol')
        elif r[0]=='PIN':
            if r[1] in pins:raise ValueError('Duplicate readback pin')
            pins[r[1]]=r
        elif r[0]=='LINE':lines.append(segment(r[1],r[2],r[3:5],r[5:7]))
        elif r[0]=='RECT':rect.append((r[1],*map(rounded,r[2:])))
        elif r[0]=='TEXT':texts.append((r[1],r[2],*map(rounded,r[3:6]),r[6].upper(),r[7]))
        elif r[0]=='FONT':fonts.append(tuple(map(rounded,r[1:])))
        elif r[0]=='HEIGHT':
            v=json.loads(r[1]) if r[1].startswith(chr(34)) else r[1]
            if isinstance(v,str):
                match=re.fullmatch(r'([0-9.]+)\s*(MM|MILLIMETERS|MIL|MILS)?',v.upper())
                if not match:raise ValueError('Invalid native height property')
                if match[2] and match[2] not in (('MM','MILLIMETERS') if s['units']=='mm' else ('MIL','MILS')):raise ValueError('Height property units mismatch')
                v=match[1]
            heights.append(rounded(v))
        elif r[0]=='TEXTBOX':textboxes.append((r[1],readback_box(r[2:])))
        else:raise ValueError(f'Unsupported native record: {r}')
    if set(pins)!={p['number'] for p in s['pins']}:raise ValueError('Pin set mismatch')
    b=s['place_bound'];lo=list(map(num,b['min']));hi=list(map(num,b['max']))
    padboxes=[]
    for p in s['pins']:
        r=pins[p['number']]
        if r[2].lower()!=p['padstack'] or list(map(rounded,r[3:6]))!=list(map(rounded,[*p['xy'],p['rotation']])) or r[6:8]!=['nil','nil']:raise ValueError(f'Pin mapping/position/rotation mismatch: {p["number"]}')
        bounds=readback_box(r[8:12]);padboxes.append(bounds)
        if bounds[0]<lo[0]-1e-6 or bounds[1]<lo[1]-1e-6 or bounds[2]>hi[0]+1e-6 or bounds[3]>hi[1]+1e-6:raise ValueError('Pad geometry extends beyond place bound')
    expected=[segment(o['layer'],o['width'],a,b) for o in s['outlines'] for a,b in zip(o['points'],o['points'][1:])]
    if Counter(lines)!=Counter(expected):raise ValueError('Outline segment geometry mismatch')
    if rect!=[(BOUND,*map(rounded,[*b['min'],*b['max']]))]:raise ValueError('Place bound mismatch')
    expected_text=[(t['layer'],t['text'],*map(rounded,[*t['xy'],t['rotation']]),'CENTER','nil') for t in s['texts']]
    if Counter(texts)!=Counter(expected_text):raise ValueError('Text content/position/orientation mismatch')
    sty=s['text_style'];expected_font=tuple(rounded(sty[k]) for k in ['width','height','line_space','char_space','stroke'])
    if fonts!=[expected_font]*len(s['texts']):raise ValueError('Text dimensions mismatch')
    if heights!=[rounded(b['height'])]:raise ValueError('Package height mismatch')
    if Counter(layer for layer,box in textboxes)!=Counter(t['layer'] for t in s['texts']):
        raise ValueError('Text bounding box layers/counts mismatch')
    clearance=num(s['silk_clearance'])
    for layer,width,(p1,p2) in lines:
        if layer.endswith('/SILKSCREEN_TOP'):
            for box in padboxes:
                if segment_box_distance(p1,p2,box)+1e-6 < clearance+width/2:raise ValueError('Silkscreen line clearance violation')
    for layer,box in textboxes:
        if layer.endswith('/SILKSCREEN_TOP'):
            for pad in padboxes:
                dx=max(pad[0]-box[2],box[0]-pad[2],0);dy=max(pad[1]-box[3],box[1]-pad[3],0)
                if math.hypot(dx,dy)+1e-6 < clearance:raise ValueError('Silkscreen text clearance violation')
    return {'pin_count':len(pins),'segments':len(lines),'texts':len(texts),'geometry_verified':True}


def load_environment(env_file=None,license_file=None):
    env=dict(os.environ)
    if env_file:
        path=Path(env_file).resolve(strict=True)
        # Source the caller-selected shell file; preserve quoting and never log
        # the full inherited environment or license contents.
        r=subprocess.run(['bash','-c','source "$1" >&2 || exit $?; env -0','bash',str(path)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=15)
        if r.returncode:raise ValueError('SPB environment script failed')
        env=dict(item.split('=',1) for item in r.stdout.decode().split('\0') if item)
    if license_file:
        env['CDS_LIC_FILE']=str(Path(license_file).resolve(strict=True))
    return env


def build(s,out,args,original=None,transform=None):
    out.mkdir(parents=True,exist_ok=False)
    if original is not None:(out/'input-spec.json').write_text(json.dumps(original,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    if transform:(out/'coordinate-transform.json').write_text(json.dumps(transform,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    result={'status':'generated_only','runs':[]}
    (out/'spec.json').write_text(json.dumps(s,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    (out/'build.il').write_text(generate(s),encoding='utf-8')
    (out/'build.scr').write_text('version 16.6\nskill load("build.il")\nexit\n',encoding='utf-8')
    shutil.copyfile(Path(__file__).with_name('readback.il'),out/'readback.il')
    try:
        result['pad_sources']={}
        for name,src in s['padstacks'].items():
            p=Path(src).resolve(strict=True)
            if not p.is_file() or not p.stat().st_size:raise ValueError('Empty PAD source')
            shutil.copyfile(p,out/(name+'.pad'))
            result['pad_sources'][name]={'path':str(p),'sha256':digest(p)}
        if args.execute:
            if not args.cadence_root:raise ValueError('--cadence-root is required for native execution')
            b=Path(args.cadence_root).resolve(strict=True)/'tools.lnx86/bin'
            env=load_environment(args.env_file,args.license_file)
            env.update(CDSROOT=str(b.parents[1]),CDS_AUTO_64BIT='ALL',PATH=str(b)+':'+env.get('PATH',''))
            result['environment']={'env_file':str(args.env_file) if args.env_file else None,'env_file_sha256':digest(args.env_file) if args.env_file else None,'license_configured':bool(env.get('CDS_LIC_FILE') or env.get('LM_LICENSE_FILE')),'cadence_root':str(b.parents[1])}
            for k in ['DISPLAY','WAYLAND_DISPLAY','LD_PRELOAD']:env.pop(k,None)
            def run(cmd,cwd,label,editor=False,done=None):
                e=dict(env,ALLEGRO_MWUSER_DIR=str(cwd/'mw'))
                r=native_run(cmd,cwd,e,args.timeout,cwd/(label+'.log'),args.cleanup_ended_session if editor else False,cwd/done if done else None)
                result['runs'].append(r)
                if r['timed_out'] or r['remaining_native_pids'] or (r['returncode']!=0 and not r['ended_session_cleanup']):raise ValueError(f'{label} process failed')
                if editor:
                    journal=(cwd/'allegro.jrl').read_text(errors='replace')
                    if '\\e ' in journal or '*Error*' in (cwd/(label+'.log')).read_text(errors='replace'):raise ValueError(f'{label} reported an error')
                    if not done or not (cwd/done).is_file():raise ValueError(f'{label} completion marker missing')
                return r
            launcher=([str(b/'wstarter'),str(Path(__file__).with_name('compat-exec.sh').resolve()),str(b/'allegro.exe')] if args.runtime=='spb172' else [str(b/'allegro')])
            if args.starter_file:
                if args.runtime!='native':raise ValueError('--starter-file requires native runtime')
                starter=args.starter_file.resolve(strict=True)
                result['starter']={'path':str(starter),'sha256':digest(starter)}
                launcher=[str(starter),str(b/'allegro.exe')]
            editor=['xvfb-run','-a']+launcher+['-nograph','-noopengl','-safe']
            run(editor+['-symbol','package','-s','build.scr',s['name']+'.dra'],out,'editor',True,'build.done')
            result['cadence_version']=next((line for line in (out/'allegro.jrl').read_text(errors='replace').splitlines() if 'allegro ' in line),None)
            result['editor_sha256']=digest(b/'allegro.exe')
            run([str(b/'create_sym'),'-p',s['name']+'.dra',s['name']+'.psm'],out,'compile')
            if not (out/(s['name']+'.psm')).is_file():raise ValueError('No PSM')
            result['verification']={}
            for name in s['padstacks']:
                run([str(b/'report'),'-v','pad',name+'.pad','source_'+name+'.txt'],out,'report_'+name)
            for mode in (['dra','psm'] if args.pcb_product else ['dra']):
                w=out/(mode+'-check');w.mkdir()
                shutil.copyfile(out/'readback.il',w/'readback.il')
                if mode=='dra':shutil.copyfile(out/(s['name']+'.dra'),w/(s['name']+'.dra'))
                else:
                    shutil.copyfile(out/(s['name']+'.psm'),w/(s['name']+'.psm'))
                    for name in s['padstacks']:shutil.copyfile(out/(name+'.pad'),w/(name+'.pad'))
                commands=['version 16.6','skill load("readback.il")']
                if mode=='psm':commands.append(f'skill axlDBChangeDesignUnits({q("millimeters" if s["units"]=="mm" else "mils")} {s["accuracy"]})')
                commands += [f'skill pkgReadback({q(mode)} {q(s["name"])} "readback.txt")','exit']
                (w/'verify.scr').write_text('\n'.join(commands)+'\n',encoding='utf-8')
                cmd=editor+(['-symbol','package'] if mode=='dra' else ['-product',args.pcb_product])+['-s','verify.scr',s['name']+'.dra' if mode=='dra' else 'check.brd']
                run(cmd,w,mode,True,mode+'.done')
                result['verification'][mode]=verify(s,w/'readback.txt')
                for name in s['padstacks']:
                    run([str(b/'report'),'-v','pad',mode+'_'+name+'.pad','pad_'+name+'.txt'],w,'report_'+name)
                    if pad_signature(out/('source_'+name+'.txt'))!=pad_signature(w/('pad_'+name+'.txt')):raise ValueError('Embedded pad geometry differs from source: '+name)
                result['verification'][mode]['embedded_pads_verified']=True
                if mode=='psm':
                    placed=(w/'placement.txt').read_text().strip().split('|')
                    if placed!=['PLACED',s['name'].upper(),'0.000000','0.000000','0.000000',str(len(s['pins']))]:raise ValueError('PSM placement mismatch')
                    if not (w/'psm-load-check.brd').is_file():raise ValueError('PSM placement board not saved')
                    result['verification'][mode]['placed_on_pcb']=True
            result['psm_validation']='native_compile_and_pcb_readback' if args.pcb_product else 'native_compile_only'
            result['ended_session_cleanup']=any(r['ended_session_cleanup'] for r in result['runs'])
            result['status']='verified' if args.pcb_product else 'verified_dra_psm_compiled'
    except (ValueError,OSError,TypeError) as e:
        result['status']='failed';result['error']=str(e)
    result['files']={str(p.relative_to(out)):{'size':p.stat().st_size,'sha256':digest(p)} for p in sorted(out.rglob('*')) if p.is_file() and not p.is_symlink()}
    (out/'result.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    b=sub.add_parser('build');b.add_argument('spec',type=Path);b.add_argument('--out',type=Path,required=True);b.add_argument('--execute',action='store_true')
    b.add_argument('--cadence-root',default=None);b.add_argument('--timeout',type=float,default=45)
    b.add_argument('--runtime',choices=['spb172','native'],default='spb172',help='Explicit runtime profile; native omits 17.2 library preloads; SPB24 host launcher adaptation is documented in references/runtime.md')
    b.add_argument('--env-file',type=Path,help='Source this existing SPB bash environment file before running Cadence')
    b.add_argument('--starter-file',type=Path,help='Explicit audited native launcher taking the editor executable as its first argument')
    b.add_argument('--license-file',type=Path,help='Use this existing license file only for the job processes')
    b.add_argument('--pcb-product',help='Optional licensed PCB product: also load PSM into a fresh PCB database and verify it')
    b.add_argument('--cleanup-ended-session',action='store_true',help='Reclaim own 17.2 P25 editor after journal Exit/end and job completion marker')
    v=sub.add_parser('verify');v.add_argument('spec',type=Path);v.add_argument('readback',type=Path)
    args=p.parse_args()
    try:
        original=json.loads(args.spec.read_text(encoding='utf-8'))
        s,transform=normalize_measurement(original)
        s=validate(s)
        if args.command=='build':
            if args.cleanup_ended_session and args.runtime!='spb172':raise ValueError('P25 exit cleanup requires spb172 runtime')
            if not 5<=args.timeout<=300:raise ValueError('timeout must be 5..300 seconds')
            result=build(s,args.out.resolve(),args,original,transform)
        else:result=verify(s,args.readback)
        summary={k:v for k,v in result.items() if k not in ('files','runs','pad_sources')}
        if args.command=='build':summary['result_path']=str(args.out.resolve()/'result.json')
        print(json.dumps(summary,indent=2,ensure_ascii=False));return 1 if result.get('status')=='failed' else 0
    except (ValueError,OSError,TypeError,KeyError) as e:print(json.dumps({'status':'failed','error':str(e)}));return 1

if __name__=='__main__':sys.exit(main())
