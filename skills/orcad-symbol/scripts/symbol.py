#!/usr/bin/env python3
"""Portable Capture library XML authoring; no Cadence runtime or network side effects."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

XSI = 'http://www.w3.org/2001/XMLSchema-instance'
ET.register_namespace('xsi', XSI)
ROLES = {'signal_input','signal_output','bidirectional','passive','power_input','power_output','power_return','no_connect','internal_switch','thermal'}
TYPES = {'INPUT','OUTPUT','BIDIRECTIONAL','3STATE','PASSIVE','OPEN_COLLECTOR','OPEN_EMITTER','POWER'}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def exact(d, required, optional=()):
    require(isinstance(d,dict), 'object required')
    require(set(required) <= d.keys(), 'missing fields: '+str(set(required)-d.keys()))
    require(d.keys() <= set(required)|set(optional), 'unknown fields: '+str(d.keys()-set(required)-set(optional)))


def string(x):
    require(isinstance(x,str) and x.strip() and all(ord(c)>=32 for c in x), 'nonempty XML-safe text required')
    return x


def validate(s, profile):
    exact(s, ['schema','name','refdes','footprint','sources','units','body','pins'])
    require(s['schema']==1, 'schema must be 1')
    require(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]{0,63}',s['name']) is not None,'invalid name')
    require(re.fullmatch(r'[A-Za-z]+',s['refdes']) is not None,'refdes prefix must be alphabetic')
    require(isinstance(s['footprint'],str), 'footprint string required')
    require(s['units']=='capture_db', 'only explicit Capture database coordinates supported')
    require(isinstance(s['sources'],list) and s['sources'], 'datasheet provenance required')
    for source in s['sources']:
        exact(source,['location','basis']); string(source['location']); string(source['basis'])
    exact(profile,['schema','basis','types'])
    require(profile['schema']==1,'profile schema must be 1'); string(profile['basis'])
    require(isinstance(profile['types'],dict) and profile['types'], 'type mapping required')
    for k,v in profile['types'].items():
        require(k in TYPES and type(v) is int and 0<=v<=255,'invalid enum profile')
    require(len(set(profile['types'].values()))==len(profile['types']), 'enum aliases are not supported')
    body=s['body']; require(isinstance(body,list) and len(body)==4 and all(type(x)is int for x in body),'body [x1,y1,x2,y2] integers required')
    x1,y1,x2,y2=body; require(x2>x1 and y2>y1, 'invalid body bounds')
    require(isinstance(s['pins'],list) and s['pins'], 'pins required')
    numbers=set(); points=set()
    for p in s['pins']:
        exact(p,['number','name','role','capture_type','visible','implicit_net','no_connect','side','offset','basis'])
        require(re.fullmatch(r'[A-Za-z0-9_]+',p['number']) is not None, 'one physical pin number per pin required')
        require(p['number'].casefold() not in numbers,'duplicate physical number'); numbers.add(p['number'].casefold())
        string(p['name']); string(p['basis'])
        require(p['role'] in ROLES,'unknown semantic role')
        require(p['capture_type'] in profile['types'],'capture_type lacks evidenced mapping: '+p['capture_type'])
        require(p['visible'] is True and p['implicit_net'] is None,'v1 requires visible explicitly wired pins; hidden/implicit power unsupported')
        require(type(p['no_connect']) is bool,'no_connect must be boolean')
        require(p['no_connect']==(p['role']=='no_connect'),'NC marker must match verified no_connect role, not pin name')
        if p['role'].startswith('power_'):
            require(p['capture_type']=='POWER','supply/return pins must retain Capture POWER type; direction is separate metadata')
        if p['role']=='signal_input': require(p['capture_type']=='INPUT','signal input must map to INPUT')
        if p['role']=='signal_output': require(p['capture_type'] in {'OUTPUT','OPEN_COLLECTOR','OPEN_EMITTER','3STATE'},'output needs explicit driver type')
        if p['role']=='bidirectional': require(p['capture_type']=='BIDIRECTIONAL','bidirectional must map to BIDIRECTIONAL')
        if p['role'] in {'passive','thermal','internal_switch','no_connect'}: require(p['capture_type']=='PASSIVE','non-signal role requires explicit passive terminal')
        require(p['side'] in {'left','right','top','bottom'} and type(p['offset'])is int, 'invalid pin placement')
        lo,hi=(y1,y2) if p['side'] in {'left','right'} else (x1,x2)
        require(lo<p['offset']<hi, 'pin must be on body edge away from corners')
        point=(p['side'],p['offset']); require(point not in points,'stacked pins unsupported; keep each number visible'); points.add(point)
    return s


def obj(parent,tag,**attrs):
    e=ET.SubElement(parent,tag); ET.SubElement(e,'Defn',{k:str(v) for k,v in attrs.items()}); return e


def build(s,profile):
    validate(s,profile)
    root=ET.Element('Lib',{f'{{{XSI}}}noNamespaceSchemaLocation':'olb.xsd'})
    ET.SubElement(root,'Defn',name=s['name']+'.olb')
    package=obj(root,'Package',alphabeticNumbering=2,isHomogeneous=1,name=s['name'],refdesPrefix=s['refdes'],pcbFootprint=s['footprint'])
    part=obj(package,'LibPart'); view=obj(part,'NormalView',suffix='.Normal')
    x1,y1,x2,y2=s['body']; obj(view,'SymbolBBox',x1=x1,y1=y1,x2=x2,y2=y2)
    for tag in ('IsPinNumbersVisible','IsPinNamesVisible','IsPinNamesRotated'): obj(view,tag,val=1)
    obj(view,'PartValue',name=s['name']); obj(view,'Reference',name=s['refdes'])
    for a,b in [((x1,y1),(x2,y1)),((x2,y1),(x2,y2)),((x2,y2),(x1,y2)),((x1,y2),(x1,y1))]:
        obj(view,'Line',lineStyle=0,lineWidth=0,x1=a[0],y1=a[1],x2=b[0],y2=b[1])
    physical=obj(part,'PhysicalPart')
    for index,p in enumerate(s['pins']):
        t=p['offset']; start,hot={'left':((x1,t),(x1-20,t)), 'right':((x2,t),(x2+20,t)), 'top':((t,y1),(t,y1-20)), 'bottom':((t,y2),(t,y2+20))}[p['side']]
        pin=obj(view,'SymbolPinScalar',hotptX=hot[0],hotptY=hot[1],name=p['name'],position=index,startX=start[0],startY=start[1],type=profile['types'][p['capture_type']],visible=1)
        for tag in ('IsLong','IsClock','IsDot','IsLeftPointing','IsRightPointing','IsNetStyle','IsGlobal'): obj(pin,tag,val=0)
        obj(pin,'IsNoConnect',val=int(p['no_connect'])); obj(pin,'IsNumberVisible',val=1)
        obj(pin,'PinUserProp',name='AgentElectricalRole',val=p['role'])
        obj(pin,'PinUserProp',name='AgentEvidence',val=p['basis'])
        obj(physical,'PinNumber',number=p['number'],position=index)
    ET.indent(root)
    return root


class NoDTDTreeBuilder(ET.TreeBuilder):
    def doctype(self, name, pubid, system):
        raise ValueError('DTD/entities unsupported')


def read_xml(path):
    b=Path(path).read_bytes()
    require(len(b)<32*1024*1024,'XML too large')
    # Reject declarations after XML encoding detection, including UTF-16 input.
    return ET.fromstring(b, parser=ET.XMLParser(target=NoDTDTreeBuilder()))


def inspect(root):
    require(root.tag=='Lib','Capture Lib XML required; OLB binary requires native export first')
    result=[]
    for package in root.findall('Package'):
        for part in package.findall('LibPart'):
            physical=part.findall('PhysicalPart')
            require(len(physical)==1,'inspect v1 requires one physical part per unit')
            number_list=[e.attrib for e in physical[0].findall('PinNumber/Defn')]
            numbers={e['position']:e['number'] for e in number_list}
            require(len(numbers)==len(number_list),'duplicate pin mapping position')
            for view in part.findall('NormalView'):
                pins=[]; seen=set()
                for pin in view.findall('SymbolPinScalar'):
                    d=dict(pin.find('Defn').attrib); pos=d['position']
                    require(pos in numbers and pos not in seen, 'missing/duplicate physical pin position'); seen.add(pos)
                    d['number']=numbers[pos]
                    for tag in ('IsGlobal','IsNoConnect','IsNumberVisible','IsClock','IsDot','IsLong','IsLeftPointing','IsRightPointing','IsNetStyle'):
                        e=pin.find(tag+'/Defn'); d[tag]=None if e is None else e.get('val')
                    d['properties']={p.get('name'):p.get('val') for p in pin.findall('PinUserProp/Defn')}
                    pins.append(d)
                require(seen==numbers.keys(),'orphan physical number')
                result.append({'name':package.find('Defn').get('name'),'suffix':view.find('Defn').get('suffix'),'pins':pins})
    require(result,'no package normal views found')
    return result


def verify(s,profile,root):
    generated=build(s,profile)
    expected=inspect(generated); actual=inspect(root)
    require(actual==expected,'XML pin readback differs: number/name/type/visibility/connection/geometry/evidence')
    # Structural compare generated subset catches body, package and view settings as well.
    for path in ['Package/Defn','Package/LibPart/NormalView/SymbolBBox/Defn','Package/LibPart/NormalView/IsPinNamesVisible/Defn','Package/LibPart/NormalView/IsPinNamesRotated/Defn','Package/LibPart/NormalView/IsPinNumbersVisible/Defn','Package/LibPart/NormalView/PartValue/Defn','Package/LibPart/NormalView/Reference/Defn']:
        a=root.find(path); b=generated.find(path)
        require(a is not None and a.attrib==b.attrib, 'XML differs at '+path)
    linepath='Package/LibPart/NormalView/Line/Defn'
    require([e.attrib for e in root.findall(linepath)]==[e.attrib for e in generated.findall(linepath)],'body outline geometry differs')
    require(not root.findall('.//ConvertView') and not root.findall('.//SymbolPinBus'),'alternate views and bus pins require separate review')
    return {'status':'offline_semantics_verified','native_capture_verified':False,'pins':len(s['pins'])}


def main():
    parser=argparse.ArgumentParser(description=__doc__); sub=parser.add_subparsers(dest='cmd',required=True)
    b=sub.add_parser('build'); b.add_argument('spec'); b.add_argument('--profile',required=True); b.add_argument('--out',required=True)
    i=sub.add_parser('inspect'); i.add_argument('xml')
    v=sub.add_parser('verify'); v.add_argument('spec'); v.add_argument('xml'); v.add_argument('--profile',required=True)
    a=parser.parse_args()
    try:
        if a.cmd=='inspect': result=inspect(read_xml(a.xml))
        else:
            s=json.loads(Path(a.spec).read_text(encoding='utf-8')); profile=json.loads(Path(a.profile).read_text(encoding='utf-8'))
            if a.cmd=='build':
                root=build(s,profile); out=Path(a.out); require(not out.exists(),'output directory must be new'); out.mkdir(parents=True)
                xml=out/(s['name']+'.xml'); ET.ElementTree(root).write(xml,encoding='utf-8',xml_declaration=True)
                result=verify(s,profile,read_xml(xml)); result['xml_sha256']=hashlib.sha256(xml.read_bytes()).hexdigest()
                (out/'spec.json').write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding='utf-8')
                (out/'profile.json').write_text(json.dumps(profile,ensure_ascii=False,indent=2),encoding='utf-8')
                (out/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
            else: result=verify(s,profile,read_xml(a.xml))
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    except (ValueError,KeyError,TypeError,OSError,ET.ParseError) as e:
        print(json.dumps({'status':'failed','error':str(e)},ensure_ascii=False),file=sys.stderr); return 2

if __name__=='__main__': sys.exit(main())
