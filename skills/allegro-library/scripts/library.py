#!/usr/bin/env python3
"""Portable preparation and headless native extraction of Allegro PAD/DRA copies."""
import copy
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET


def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def write_json(p, value): p.write_text(json.dumps(value, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
def q(value): return json.dumps(value, ensure_ascii=True)
def point(value): return atom(value[0])+':'+atom(value[1])
def atom(v):
    if v is None: return 'nil'
    if v is True: return 't'
    if isinstance(v, str): return q(v)
    if isinstance(v, list): return 'list('+ ' '.join(atom(x) for x in v)+')'
    if not isinstance(v, (int,float)) or not (-1e9 < v < 1e9): raise ValueError('Invalid numeric value')
    text=format(v,'.12g')
    return text if '.' in text or 'e' in text.lower() else text+'.0'


def sexprs(text):
    """Read data printed with %L, never evaluate SKILL source."""
    tokens = re.findall(r'"(?:\\.|[^"\\])*"|[()]|[^\s()]+', text)
    pos=0
    def parse():
        nonlocal pos
        if pos>=len(tokens): raise ValueError('Truncated snapshot')
        tok=tokens[pos];pos+=1
        if tok=='(':
            out=[]
            while pos<len(tokens) and tokens[pos]!=')': out.append(parse())
            if pos==len(tokens): raise ValueError('Unclosed snapshot list')
            pos+=1; return out
        if tok==')': raise ValueError('Unexpected closing parenthesis')
        if tok.startswith('"'): return json.loads(tok)
        if tok=='nil': return None
        if tok=='t': return True
        if re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?',tok): return float(tok)
        raise ValueError('Unsupported snapshot atom: '+tok)
    result=[]
    while pos<len(tokens): result.append(parse())
    if not result or result[-1]!=['end']: raise ValueError('Missing snapshot end marker')
    return result


def canonical(records):
    """Compare geometry as a multiset; ignore DB object ordering and line direction."""
    def seg(s):
        s=list(s)
        if s[0]=='line': s[2:4]=sorted(s[2:4])
        elif s[0]=='arc' and not s[6] and s[3]<s[2]:
            s[2],s[3]=s[3],s[2];s[5]=None if s[5] else True
        return s
    def numbers(v):
        if isinstance(v,list):return [numbers(x) for x in v]
        if type(v) in (int,float):return float(v)
        return v
    norm=[]
    for r in records:
        r=list(r)
        if r[0]=='pin': r[2]=r[2].lower()
        if r[0]=='path': r[2]=sorted([seg(s) for s in r[2]],key=q)
        if r[0]=='shape': r[4]=sorted([seg(s) for s in r[4]],key=q)
        norm.append(q(numbers(r)))
    return Counter(norm)


def rebuild(records):
    types=[r[1].upper() for r in records if r[0]=='type']
    if len(types)!=1 or types[0] not in ('PACKAGE','SHAPE','FLASH'):raise ValueError('Unsupported DRA type')
    if types[0] in ('SHAPE','FLASH'):
        shapes=[r for r in records if r[0]=='shape']
        if not shapes or (types[0]=='SHAPE' and len(shapes)!=1):raise ValueError('SHAPE requires exactly one solid shape; FLASH requires explicit apertures')
        if any(r[0] not in ('units','type','shape','end') for r in records):raise ValueError('Unsupported object in SHAPE/FLASH')
        if any(r[2] is not True or r[3] or not r[1].upper().startswith('ETCH/') for r in shapes):raise ValueError('SHAPE/FLASH requires solid, void-free ETCH geometry')
    code=['; Reconstructed geometry, not the original interactive history.',
          'procedure(libRebuild() let((tb p r f)',
          'axlSetVariable("padpath" ".")',
          'axlSetVariable("psmpath" ".")',
          'unless(axlDBChangeDesignExtents(list(-10000:-10000 10000:10000)) error("Extents failed"))']
    def require(expr): code.append('unless('+expr+' error("Reconstruction failed"))')
    def path(segments):
        if not segments: raise ValueError('Empty path')
        code.append('p=axlPathStart(list('+point(segments[0][2])+') '+atom(segments[0][1])+')')
        for s in segments:
            if s[0] not in ('line','arc') or s[-1] is not None: raise ValueError('Unsupported segment or non-solid line font')
            if s[0]=='line': require('axlPathLine(p '+atom(s[1])+' '+point(s[3])+')')
            else: require('axlPathArcCenter(p '+atom(s[1])+' '+point(s[3])+' '+atom(s[5])+' '+point(s[4])+')')
    for r in records:
        tag=r[0]
        if tag=='units': require('axlDBChangeDesignUnits('+q(r[1])+' '+str(int(r[2]))+')')
        elif tag=='type':
            pass
        elif tag=='pin':
            if r[5] or r[6]: raise ValueError('Mirrored/mechanical pin unsupported')
            require('axlDBCreatePin('+q(r[2].lower())+' '+atom(r[3])+' make_axlPinText(?number '+q(r[1])+' ?offset 0:0 ?text "1") '+atom(r[4])+')')
        elif tag=='path':
            path(r[2]);require('axlDBCreatePath(p '+q(r[1])+')')
        elif tag=='shape':
            if r[2] not in (True,None) or r[3] or r[6]: raise ValueError('Voided, hatched or dynamic shape unsupported')
            path(r[4]);code.append('r=axlDBCreateShape(p '+atom(r[2])+' '+q(r[1])+')');require('r')
            if r[5] is not None: require('axlDBAddProp(car(r) list(list("PACKAGE_HEIGHT_MAX" '+atom(r[5])+')))')
        elif tag=='text':
            vals=' '.join('?'+key+' '+atom(val) for key,val in zip(['width','height','lineSpace','charSpace','photoWidth'],r[7]))
            code.append('tb=axlDBTextBlockCreate(1 '+vals+')');require('tb')
            require('axlDBCreateText('+q(r[2])+' '+atom(r[3])+' make_axlTextOrientation(?textBlock sprintf(nil "%d" tb) ?rotation '+atom(r[4])+' ?justify '+q(r[5])+' ?mirrored '+atom(r[6])+') '+q(r[1])+')')
        elif tag in ('end','padpoly'): pass
        else: raise ValueError('Unsupported database object: '+str(r))
    require('axlSaveDesign(?design "reconstructed.dra" ?noMru t)')
    code+=['f=outfile("build.done") fprintf(f "done\\n") close(f)', '))','libRebuild()']
    return '\n'.join(code)+'\n'


def pad_signature(p):
    text=p.read_text(errors='replace');lines=text.splitlines()
    units=next(x for x in lines if x.startswith('Dimensions in '))
    kind=next(x.split(' Type: ',1)[1] for x in lines if x.startswith('Padstack: '))
    start=next(i for i,x in enumerate(lines) if x.startswith('Layer,Pad Type,'))
    return [units,kind]+sorted(x.strip() for x in lines[start:] if x.strip() and not x.startswith('Drill Data for '))


def normalize_measurement(spec):
    s=copy.deepcopy(spec);m=s.pop('measurement',None)
    if m is None:return s,None
    if not isinstance(m,dict) or not set(m)<={'basis','copper_bounds'} or not isinstance(m.get('basis'),str) or not m['basis'].strip():raise ValueError('Measurement basis required')
    if 'copper_bounds' in m:
        b=m['copper_bounds']
        if not isinstance(b,dict) or set(b)!={'min','max'}:raise ValueError('copper_bounds needs min/max')
        lo,hi=b['min'],b['max']
    else:
        if s['type']!='shape':raise ValueError('FLASH must use copper_bounds; never recenter paste windows independently')
        pts=[p for poly in s['polygons'] for p in poly]
        lo=[min(p[i] for p in pts) for i in (0,1)];hi=[max(p[i] for p in pts) for i in (0,1)]
    if any(not isinstance(p,list) or len(p)!=2 or any(type(x) not in (int,float) or not -10000<x<10000 for x in p) for p in (lo,hi)):raise ValueError('Finite copper bounds required')
    if any(x>=y for x,y in zip(lo,hi)):raise ValueError('Invalid copper bounds')
    c=[(x+y)/2 for x,y in zip(lo,hi)]
    s['polygons']=[[[round(x-c[i],10) for i,x in enumerate(p)] for p in poly] for poly in s['polygons']]
    record={'definition':'copper_bbox_center','source_center':c,'translation':[-x for x in c],'units':s['units'],'basis':m['basis']}
    s['sources'].append({'location':'coordinate normalization','basis':json.dumps(record,ensure_ascii=False)})
    return s,record


def design_records(spec):
    required={'schema','name','type','units','accuracy','polygons','sources'}
    if not isinstance(spec,dict) or set(spec)!=required or type(spec['schema']) is not int or spec['schema']!=1:raise ValueError('Invalid shape design schema')
    if not re.fullmatch('[a-z][a-z0-9_]{0,30}',spec['name']):raise ValueError('Invalid symbol name')
    if spec['type'] not in ('shape','flash') or spec['units'] not in ('mm','mil'):raise ValueError('Invalid symbol type/units')
    if spec['type']=='flash' and len(spec['name'])>18:raise ValueError('Flash symbol name exceeds documented 18-character limit')
    acc=spec['accuracy']
    if type(acc) is not int or not 0<=acc<=4:raise ValueError('Invalid accuracy')
    if not isinstance(spec['sources'],list) or not spec['sources']:raise ValueError('Explicit dimension and process sources required')
    for source in spec['sources']:
        if not isinstance(source,dict) or not all(isinstance(source.get(k),str) and source[k].strip() for k in ('location','basis')):raise ValueError('Each source needs location and basis')
    polys=spec['polygons']
    if not isinstance(polys,list) or not 1<=len(polys)<=128 or (spec['type']=='shape' and len(polys)!=1):raise ValueError('Copper SHAPE requires one polygon; FLASH can have 1..128 separate windows')
    records=[['units','millimeters' if spec['units']=='mm' else 'mils',acc],['type',spec['type'].upper()]]
    def orientation(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    def intersects(a,b,c,d):
        if max(a[0],b[0])<min(c[0],d[0]) or max(c[0],d[0])<min(a[0],b[0]) or max(a[1],b[1])<min(c[1],d[1]) or max(c[1],d[1])<min(a[1],b[1]):return False
        return orientation(a,b,c)*orientation(a,b,d)<=0 and orientation(c,d,a)*orientation(c,d,b)<=0
    for points in polys:
        if not isinstance(points,list) or not 4<=len(points)<=1000 or points[0]!=points[-1]:raise ValueError('Explicit closed polygon required')
        for xy in points:
            if not isinstance(xy,list) or len(xy)!=2:raise ValueError('Point must be [x,y]')
            for v in xy:
                if type(v) not in (int,float) or not -10000<v<10000 or abs(v-round(v,acc))>1e-9:raise ValueError('Non-finite/out-of-range coordinate or precision loss')
        edges=list(zip(points,points[1:]))
        if any(a==b for a,b in edges):raise ValueError('Zero length polygon edge')
        for i,(a,b) in enumerate(edges):
            for j,(c,d) in enumerate(edges):
                if j>i+1 and (i,j)!=(0,len(edges)-1) and intersects(a,b,c,d):raise ValueError('Self-intersecting polygon')
        if abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in edges))<1e-9:raise ValueError('Zero area polygon')
        records.append(['shape','ETCH/TOP',True,None,[['line',0.0,a,b,None] for a,b in edges],None,None])
    def inside(p,poly):
        odd=False
        for a,b in zip(poly,poly[1:]):
            if (a[1]>p[1])!=(b[1]>p[1]) and p[0]<(b[0]-a[0])*(p[1]-a[1])/(b[1]-a[1])+a[0]:odd=not odd
        return odd
    for i,poly in enumerate(polys):
        for other in polys[i+1:]:
            if inside(poly[0],other) or inside(other[0],poly) or any(intersects(a,b,c,d) for a,b in zip(poly,poly[1:]) for c,d in zip(other,other[1:])):
                raise ValueError('Flash windows overlap or touch; provide separate non-overlapping apertures')
    records.append(['end']);return records


def design(spec,out,args):
    original=spec;spec,transform=normalize_measurement(spec)
    records=design_records(spec);code=rebuild(records)
    out.mkdir(parents=True,exist_ok=False)
    write_json(out/'input-design.json',original)
    if transform:write_json(out/'coordinate-transform.json',transform)
    write_json(out/'design.json',spec);write_json(out/'snapshot.json',records)
    (out/'rebuild.il').write_text(code,encoding='utf-8');(out/'rebuild.scr').write_text('version 16.6\nskill load("rebuild.il")\nexit\n',encoding='utf-8')
    result={'status':'generated_only','scope':'Explicit SHAPE/FLASH geometry, no inferred manufacturing dimensions'}
    if args.execute:
        n=Native(args.cadence_root.resolve(strict=True),args.display,args.timeout,args.license_file);result['runs']=n.runs
        try:
            n.call('allegro',['-nograph','-noopengl','-safe','-symbol',spec['type'],'-s','rebuild.scr','reconstructed.dra'],out,'build',True)
            if not (out/'build.done').is_file():raise ValueError('Build completion missing')
            actual=n.inspect(out,'reconstructed.dra')
            if canonical(records)!=canonical(actual):raise ValueError('Designed shape geometry readback mismatch')
            filename=spec['name']+('.ssm' if spec['type']=='shape' else '.fsm')
            n.call('create_sym',['-s' if spec['type']=='shape' else '-t','reconstructed.dra',filename],out,'compile')
            if not (out/filename).is_file():raise ValueError('Compiled symbol missing')
            result.update(status='verified_shape_design',compiled_symbol=filename)
        except (ValueError,OSError) as e:result.update(status='failed',error=str(e))
    result['files']={str(p.relative_to(out)):{'size':p.stat().st_size,'sha256':digest(p)} for p in sorted(out.rglob('*')) if p.is_file()}
    write_json(out/'result.json',result);return result


class Native:
    def __init__(self,root,display,timeout,license_file):
        system=platform.system()
        if system not in ('Linux','Windows'): raise ValueError('Prepare on this OS; run the job on a Linux/Windows Cadence worker')
        self.windows=system=='Windows';self.bin=root/('tools/bin' if self.windows else 'tools.lnx86/bin')
        self.display=display;self.timeout=timeout;self.runs=[]
        self.env=dict(os.environ,CDSROOT=str(root),CDS_AUTO_64BIT='ALL',PATH=str(self.bin)+os.pathsep+os.environ.get('PATH',''))
        if license_file:self.env['CDS_LIC_FILE']=str(license_file.resolve(strict=True))
        self.env.pop('LD_PRELOAD',None)
        if not self.windows:
            self.env.pop('DISPLAY',None);self.env.pop('WAYLAND_DISPLAY',None)
    def call(self,tool,args,cwd,label,editor=False):
        binary=self.bin/(tool+('.exe' if self.windows else ''))
        if not binary.is_file():raise ValueError('Missing native executable: '+str(binary))
        cmd=[str(binary)]+args
        if editor and not self.windows and self.display=='xvfb':cmd=['xvfb-run','-a']+cmd
        start=time.monotonic();timed_out=False
        with (cwd/(label+'.log')).open('wb') as f:
            p=subprocess.Popen(cmd,cwd=cwd,env=self.env,stdin=subprocess.DEVNULL,stdout=f,stderr=subprocess.STDOUT,
                               **({'creationflags':subprocess.CREATE_NEW_PROCESS_GROUP} if self.windows else {'start_new_session':True}))
            try: rc=p.wait(timeout=self.timeout)
            except subprocess.TimeoutExpired:
                timed_out=True
                if self.windows:subprocess.run(['taskkill','/PID',str(p.pid),'/T','/F'],stdout=f,stderr=f,check=False)
                else:os.killpg(p.pid,signal.SIGKILL)
                rc=p.wait(timeout=10)
        self.runs.append({'command':cmd,'cwd':str(cwd),'returncode':rc,'timed_out':timed_out,'seconds':round(time.monotonic()-start,2)})
        if rc or timed_out:raise ValueError('Native step failed: '+label)
    def inspect(self,cwd,dra):
        shutil.copyfile(Path(__file__).with_name('inspect.il'),cwd/'inspect.il')
        (cwd/'inspect.scr').write_text('version 16.6\nskill load("inspect.il")\nexit\n',encoding='utf-8')
        self.call('allegro',['-nograph','-noopengl','-safe','-symbol','package','-s','inspect.scr',dra],cwd,'inspect',True)
        if not (cwd/'inspect.done').is_file():raise ValueError('Native inspection did not complete')
        return sexprs((cwd/'snapshot.sexpr').read_text(encoding='utf-8',errors='strict'))


def prepare(source,out,symbols=()):
    source=source.resolve(strict=True)
    if source.suffix.lower() not in ('.pad','.dra'):raise ValueError('Expected PAD or DRA')
    out.mkdir(parents=True,exist_ok=False)
    target=out/('source'+source.suffix.lower());shutil.copyfile(source,target)
    manifest={'schema':1,'kind':source.suffix.lower()[1:],'source_name':source.name,'input':target.name,'input_sha256':digest(target),
              'scope':'PAD native pXML roundtrip or DRA geometry reconstruction; not original edit history'}
    manifest['symbols']={}
    for symbol in symbols:
        symbol=symbol.resolve(strict=True);name=symbol.name.lower()
        if symbol.suffix.lower() not in ('.ssm','.fsm') or name in manifest['symbols']:raise ValueError('Expected uniquely named SSM/FSM dependency')
        (out/'symbols').mkdir(exist_ok=True)
        shutil.copyfile(symbol,out/'symbols'/name)
        manifest['symbols'][name]=digest(out/'symbols'/name)
    write_json(out/'job.json',manifest)
    return {'status':'prepared','job':str(out),'native_executed':False}


def execute(job,args):
    meta=json.loads((job/'job.json').read_text(encoding='utf-8'))
    if meta.get('schema')!=1 or meta.get('kind') not in ('pad','dra') or meta.get('input')!='source.'+meta['kind']:raise ValueError('Invalid job manifest')
    source=job/meta['input']
    if digest(source)!=meta['input_sha256']:raise ValueError('Staged input hash mismatch')
    native_name=meta.get('source_name','')
    if not native_name or '/' in native_name or '\\' in native_name or Path(native_name).suffix.lower()!='.'+meta['kind']:
        raise ValueError('Invalid original filename')
    work=job/'native';work.mkdir(exist_ok=False);shutil.copyfile(source,work/native_name)
    for name,expected in meta.get('symbols',{}).items():
        if '/' in name or '\\' in name or Path(name).suffix.lower() not in ('.ssm','.fsm'):raise ValueError('Invalid dependency filename')
        if digest(job/'symbols'/name)!=expected:raise ValueError('Dependency hash mismatch')
        shutil.copyfile(job/'symbols'/name,work/name)
    n=Native(args.cadence_root.resolve(strict=True),args.display,args.timeout,args.license_file)
    result={'status':'failed','scope':meta['scope'],'runs':n.runs,'input_sha256':meta['input_sha256']}
    try:
        if meta['kind']=='pad':
            n.call('padstack_editor',['-xo',native_name],work,'export',True)
            xmls=list(work.glob('*.pxml'))
            if len(xmls)!=1:raise ValueError('Expected one native pXML export')
            tree=ET.parse(xmls[0]);pads=([tree.getroot()] if tree.getroot().tag=='padstack' else tree.findall('.//padstack'))
            if len(pads)!=1:raise ValueError('Expected one padstack definition')
            dependencies=[(e.tag,e.text) for e in pads[0].iter() if e.tag in ('shapename','flashname') and e.text]
            result['dependencies']=dependencies
            shutil.copyfile(xmls[0],job/'export.pxml')
            required={name.lower()+('.ssm' if tag=='shapename' else '.fsm') for tag,name in dependencies}
            missing=required-set(meta.get('symbols',{}))
            if missing:raise ValueError('pXML exported; missing explicit dependencies: '+', '.join(sorted(missing)))
            name=pads[0].findtext('padstackname')
            if not name or not re.fullmatch(r'[A-Za-z0-9_.+-]+',name) or name in ('.','..'):raise ValueError('Unsafe padstack name')
            rt=work/'roundtrip';rt.mkdir();shutil.copyfile(xmls[0],rt/'export.pxml')
            for filename in meta.get('symbols',{}):shutil.copyfile(work/filename,rt/filename)
            n.call('padstack_editor',['-x','export.pxml'],rt,'import',True)
            matches=[p for p in rt.glob('*.pad') if p.stem.casefold()==name.casefold()]
            if len(matches)!=1:raise ValueError('Native XML import did not create PAD')
            n.call('report',['-v','pad',native_name,'source-report.txt'],work,'source-report')
            n.call('report',['-v','pad',matches[0].name,'roundtrip-report.txt'],rt,'roundtrip-report')
            before=pad_signature(work/'source-report.txt');after=pad_signature(rt/'roundtrip-report.txt')
            if before!=after:
                result['report_difference']={'source_only':list((Counter(before)-Counter(after)).elements()),'roundtrip_only':list((Counter(after)-Counter(before)).elements())}
                raise ValueError('pXML exported, but native roundtrip changed PAD data; inspect report_difference')
            result['status']='verified_pad_roundtrip'
        else:
            records=n.inspect(work,native_name);write_json(job/'snapshot.json',records)
            # A supported reconstruction is not a claim to retain all database metadata.
            result['excluded_scope']=['original command history','pin-number annotation styling','arbitrary properties and constraints','3D models']
            code=rebuild(records)
            symbol_type=next(r[1].lower() for r in records if r[0]=='type')
            embedded=[]
            if symbol_type=='package':
                deps=work/'embedded-library';deps.mkdir();shutil.copyfile(work/native_name,deps/native_name)
                n.call('dump_libraries',['-pc',native_name],deps,'dependencies')
                embedded=[p for p in deps.iterdir() if p.suffix.lower() in ('.ssm','.fsm')]
                result['embedded_symbol_dependencies']={p.name:digest(p) for p in embedded}
            (job/'rebuild.il').write_text(code,encoding='utf-8')
            (job/'rebuild.scr').write_text('version 16.6\nskill load("rebuild.il")\nexit\n',encoding='utf-8')
            rt=work/'roundtrip';rt.mkdir()
            for filename in meta.get('symbols',{}):shutil.copyfile(work/filename,rt/filename)
            for dep in embedded:shutil.copyfile(dep,rt/dep.name.lower())
            for filename in ('rebuild.il','rebuild.scr'):shutil.copyfile(job/filename,rt/filename)
            pads=list(work.glob('pad_*.pad'))
            for pad in pads:shutil.copyfile(pad,rt/pad.name[4:])
            n.call('allegro',['-nograph','-noopengl','-safe','-symbol',symbol_type,'-s','rebuild.scr','reconstructed.dra'],rt,'rebuild',True)
            if not (rt/'build.done').is_file():raise ValueError('Rebuild completion marker missing')
            check=work/'check';check.mkdir();shutil.copyfile(rt/'reconstructed.dra',check/'reconstructed.dra')
            actual=n.inspect(check,'reconstructed.dra');write_json(job/'roundtrip-snapshot.json',actual)
            before_geometry,after_geometry=canonical(records),canonical(actual)
            if before_geometry!=after_geometry:
                result['geometry_difference']={
                    'source_only':[json.loads(r) for r in (before_geometry-after_geometry).elements()],
                    'roundtrip_only':[json.loads(r) for r in (after_geometry-before_geometry).elements()]}
                raise ValueError('DRA roundtrip geometry mismatch')
            for pad in pads:
                n.call('report',['-v','pad',pad.name,pad.stem+'.txt'],work,'report-'+pad.stem)
                other=check/pad.name
                if not other.is_file():raise ValueError('Embedded PAD missing after reconstruction')
                n.call('report',['-v','pad',pad.name,pad.stem+'.txt'],check,'report-'+pad.stem)
                if pad_signature(work/(pad.stem+'.txt'))!=pad_signature(check/(pad.stem+'.txt')):raise ValueError('Embedded PAD changed')
            extension={'package':'psm','shape':'ssm','flash':'fsm'}[symbol_type]
            output_name=Path(native_name).stem.lower()+'.'+extension
            n.call('create_sym',[{'package':'-p','shape':'-s','flash':'-t'}[symbol_type],'reconstructed.dra',output_name],rt,'compile')
            if not (rt/output_name).is_file():raise ValueError('Native compiled symbol missing')
            result.update(status='verified_dra_geometry_roundtrip',symbol_type=symbol_type,compiled_symbol=str((rt/output_name).relative_to(job)),embedded_pads_verified=bool(pads))
    except (ValueError,OSError,StopIteration,ET.ParseError) as e:result['error']=str(e)
    finally:
        result['staged_input_unchanged']=digest(source)==meta['input_sha256']
        if not result['staged_input_unchanged']:result.update(status='failed',error='Staged source changed')
        result['files']={str(p.relative_to(job)):{'size':p.stat().st_size,'sha256':digest(p)} for p in sorted(job.rglob('*')) if p.is_file() and p.name!='result.json'}
        write_json(job/'result.json',result)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('prepare');a.add_argument('source',type=Path);a.add_argument('--out',type=Path,required=True)
    a.add_argument('--symbol',type=Path,action='append',default=[],help='Explicit SSM/FSM dependency; repeat as needed')
    a=sub.add_parser('run');a.add_argument('job',type=Path);a.add_argument('--cadence-root',type=Path,required=True)
    a.add_argument('--display',choices=['none','xvfb'],default='xvfb');a.add_argument('--timeout',type=float,default=60);a.add_argument('--license-file',type=Path)
    a=sub.add_parser('design');a.add_argument('spec',type=Path);a.add_argument('--out',type=Path,required=True);a.add_argument('--execute',action='store_true')
    a.add_argument('--cadence-root',type=Path);a.add_argument('--display',choices=['none','xvfb'],default='xvfb');a.add_argument('--timeout',type=float,default=60);a.add_argument('--license-file',type=Path)
    args=p.parse_args()
    try:
        if args.command=='prepare':result=prepare(args.source,args.out.resolve(),args.symbol)
        elif args.command=='design':
            if args.execute and not args.cadence_root:raise ValueError('--execute requires --cadence-root')
            if not 5<=args.timeout<=300:raise ValueError('Timeout must be 5..300 seconds')
            result=design(json.loads(args.spec.read_text(encoding='utf-8')),args.out.resolve(),args)
        else:
            if not 5<=args.timeout<=300:raise ValueError('Timeout must be 5..300 seconds')
            result=execute(args.job.resolve(),args)
        print(json.dumps({k:v for k,v in result.items() if k not in ('files','runs')},indent=2,ensure_ascii=False))
        return int(result['status']=='failed')
    except (ValueError,OSError) as e:print(json.dumps({'status':'failed','error':str(e)}));return 1

if __name__=='__main__':sys.exit(main())
