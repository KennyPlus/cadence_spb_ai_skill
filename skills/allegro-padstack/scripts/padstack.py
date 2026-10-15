#!/usr/bin/env python3
"""Deterministic pad specification compiler and Cadence readback verifier."""
import argparse
import csv
import copy
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

LAYERS = {'begin': 'BEGIN LAYER', 'internal': 'internal_pad_def', 'end': 'END LAYER',
          'mask_top': 'SOLDERMASK_TOP', 'mask_bottom': 'SOLDERMASK_BOTTOM',
          'paste_top': 'PASTEMASK_TOP', 'paste_bottom': 'PASTEMASK_BOTTOM'}
XML_LAYERS = {'begin': 'BEGIN_LAYER', 'mask_top': 'TOP_SOLDER_MASK_PAD',
              'paste_top': 'TOP_PASTE_MASK_PAD'}


def number(value):
    if isinstance(value, bool):
        raise ValueError('boolean is not a dimension')
    try:
        d = Decimal(str(value))
    except InvalidOperation as e:
        raise ValueError('invalid dimension') from e
    if not d.is_finite():
        raise ValueError('dimension must be finite')
    return d


def fmt(value):
    return format(number(value), 'f')


def keys(obj, allowed, required):
    if not isinstance(obj, dict) or set(obj) - set(allowed) or set(required) - set(obj):
        raise ValueError(f'expected keys {required}; allowed {allowed}')


def normalize_measurement(spec):
    """Translate measured layer centres into the BEGIN copper centre frame."""
    s=copy.deepcopy(spec)
    m=s.pop('measurement',None)
    if m is None:return s,None
    keys(m,['layer_centers','layer_bounds','basis','drill_center'],['basis'])
    if ('layer_centers' in m)==('layer_bounds' in m):raise ValueError('Provide exactly one of layer_centers or layer_bounds')
    if not isinstance(m['basis'],str) or not m['basis'].strip():raise ValueError('Measurement basis required')
    centers=m.get('layer_centers')
    if 'layer_bounds' in m:
        centers={}
        if not isinstance(m['layer_bounds'],dict):raise ValueError('layer_bounds must be an object')
        for k,b in m['layer_bounds'].items():
            keys(b,['min','max'],['min','max'])
            if any(not isinstance(b[t],list) or len(b[t])!=2 for t in ('min','max')):raise ValueError('Bounds need two points')
            lo=[number(x) for x in b['min']];hi=[number(x) for x in b['max']]
            if any(x>=y for x,y in zip(lo,hi)):raise ValueError('Invalid layer bounds')
            if k not in s['pads'] or s['pads'][k] is None:raise ValueError('Bounds for absent layer')
            if [y-x for x,y in zip(lo,hi)]!=[number(s['pads'][k][t]) for t in ('width','height')]:raise ValueError('Bounds disagree with pad dimensions')
            centers[k]=[str((x+y)/2) for x,y in zip(lo,hi)]
    required={k for k,v in s['pads'].items() if v is not None}
    if not isinstance(centers,dict) or set(centers)!=required:raise ValueError('Explicit measured center required for every present layer')
    def xy(v):
        if not isinstance(v,list) or len(v)!=2:raise ValueError('Measured center must be [x,y]')
        return [number(x) for x in v]
    center=xy(centers['begin']); offsets={}
    for k,g in s['pads'].items():
        if g is None:continue
        if 'offset' in g:raise ValueError('Do not mix measured centers and normalized offsets')
        delta=[x-c for x,c in zip(xy(centers[k]),center)]
        g['offset']=[float(x) for x in delta];offsets[k]=g['offset']
    if s['kind']!='smd':
        if 'drill_center' not in m or xy(m['drill_center'])!=center:raise ValueError('Current hole backend requires drill coaxial with copper center')
    elif 'drill_center' in m:raise ValueError('SMD has no drill center')
    record={'definition':'begin_copper_bbox_center','source_center':[float(x) for x in center],
            'translation':[float(-x) for x in center],'layer_offsets':offsets,'units':s['units'],'basis':m['basis']}
    s['sources'].append({'location':'coordinate normalization','basis':json.dumps(record,ensure_ascii=False)})
    return s,record


def validate(spec):
    keys(spec, ['schema', 'name', 'kind', 'units', 'accuracy', 'sources', 'pads', 'drill'],
         ['schema', 'name', 'kind', 'units', 'accuracy', 'sources', 'pads'])
    if spec['schema'] != 1 or not re.fullmatch(r'[a-z][a-z0-9_]{0,30}', spec['name']):
        raise ValueError('schema must be 1; name: lowercase ASCII, max 31 characters')
    if spec['kind'] not in ('smd', 'thru', 'mounting') or spec['units'] not in ('mm', 'mil'):
        raise ValueError('kind must be smd/thru/mounting; units must be mm/mil')
    if type(spec['accuracy']) is not int or not 0 <= spec['accuracy'] <= 4:
        raise ValueError('accuracy must be integer 0..4')
    if not isinstance(spec['sources'], list) or not spec['sources']:
        raise ValueError('sources must record evidence and process decisions')
    for source in spec['sources']:
        keys(source, ['path', 'location', 'basis'], ['location', 'basis'])
        if not all(isinstance(v, str) and v.strip() for v in source.values()):
            raise ValueError('source entries must contain nonempty text')
    required = {'begin', 'mask_top', 'paste_top'} if spec['kind'] == 'smd' else set(LAYERS)
    if not isinstance(spec['pads'], dict) or set(spec['pads']) != required:
        raise ValueError(f'explicit pad layers required: {sorted(required)} (null means absent)')
    quantum = Decimal(10) ** -spec['accuracy']
    for layer, geom in spec['pads'].items():
        if geom is None:
            if layer in ('begin', 'internal', 'end'):
                raise ValueError('copper cannot be null in supported profiles')
            continue
        keys(geom, ['shape', 'width', 'height', 'offset'], ['shape', 'width', 'height'])
        if geom['shape'] not in ('rectangle', 'circle', 'square'):
            raise ValueError('supported shapes: rectangle, circle, square; no implicit shape substitution')
        off=geom.get('offset',[0,0])
        if not isinstance(off,list) or len(off)!=2 or any(number(x)%quantum for x in off):raise ValueError('Layer offsets must fit accuracy')
        if layer=='begin' and any(number(x)!=0 for x in off):raise ValueError('BEGIN copper must be centered at pad origin')
        if spec['kind']!='smd' and any(number(x)!=0 for x in off):raise ValueError('Offset layers currently require SMD XML backend')
        w, h = number(geom['width']), number(geom['height'])
        if min(w, h) <= 0 or w % quantum or h % quantum:
            raise ValueError('positive dimensions must fit declared accuracy without rounding')
        if geom['shape'] != 'rectangle' and w != h:
            raise ValueError('circle/square width must equal height')
    if spec['kind'] == 'smd':
        if 'drill' in spec:
            raise ValueError('SMD must not specify a drill')
    else:
        keys(spec.get('drill'), ['diameter', 'plating', 'plus', 'minus', 'symbol_diameter'],
             ['diameter', 'plating', 'plus', 'minus', 'symbol_diameter'])
        drill = spec['drill']
        if spec['kind'] == 'thru' and drill['plating'] != 'plated':
            raise ValueError('17.2 Thru Pin requires plating; use kind=mounting for non-plated holes')
        if drill['plating'] not in ('plated', 'non_plated'):
            raise ValueError('plating must be plated/non_plated')
        for k in ('diameter', 'plus', 'minus', 'symbol_diameter'):
            if number(drill[k]) < 0 or number(drill[k]) % quantum:
                raise ValueError('drill sizes must be nonnegative and fit accuracy')
        if number(drill['symbol_diameter']) <= 0 or number(drill['diameter']) <= 0 or number(drill['minus']) >= number(drill['diameter']):
            raise ValueError('invalid finished-hole diameter/tolerance')
        for k in ('begin', 'internal', 'end'):
            if min(number(spec['pads'][k][v]) for v in ('width', 'height')) <= number(drill['diameter']) + number(drill['plus']):
                raise ValueError('hole with positive tolerance must remain inside each copper pad')
    return spec


def pxml(spec):
    if spec['kind'] != 'smd':
        raise ValueError('pXML emission currently supports SMD only; use replay for through holes')
    root = ET.Element('padstacks')
    pad = ET.SubElement(root, 'padstack', version='1.0')
    for k, v in [('padstackname', spec['name']), ('padstackusage', 'SMD_PIN'),
                 ('units', 'millimeter' if spec['units'] == 'mm' else 'mils'), ('accuracy', spec['accuracy'])]:
        ET.SubElement(pad, k).text = str(v)
    for layer, geom in spec['pads'].items():
        if geom is None:
            continue
        p = ET.SubElement(pad, 'pad')
        for k, v in [('type', 'REGULAR_PAD'), ('layer', XML_LAYERS[layer]),
                     ('figure', geom['shape'].upper()), ('width', fmt(geom['width'])), ('height', fmt(geom['height']))]:
            ET.SubElement(p, k).text = v
        off=geom.get('offset',[0,0])
        ET.SubElement(p,'offset').text='('+fmt(off[0])+';'+fmt(off[1])+')'
    ET.indent(root)
    return ET.tostring(root, encoding='unicode', xml_declaration=True) + '\n'


def replay(spec, mask_column='Pad'):
    if any(g and any(number(x)!=0 for x in g.get('offset',[0,0])) for g in spec['pads'].values()):raise ValueError('Nonzero layer offsets require --backend xml; replay offset controls are not verified')
    smd = spec['kind'] == 'smd'
    kind, index = {'smd': ('SMD Pin', 1), 'thru': ('Thru Pin', 0), 'mounting': ('Mounting Hole', 7)}[spec['kind']]
    lines = [f'QtSignal GuidedTabsParent PadstackTypes currentRowChanged {index}',
             f'QtSignal GuidedTabsParent PadstackTypes itemSelectionChanged "{kind}"',
             f'QtSignal GuidedTabsParent PadstackTypes itemClicked "{kind}"',
             'QtSignal MainWindow Units CurrentIndexChanged ' + ('Millimeter' if spec['units'] == 'mm' else 'Mils'),
             'QtFillin Yes', f'QtSignal MainWindow DecimalPlaces CurrentIndexChanged {spec["accuracy"]}']
    def emit_geometry(parent, row, label, geom):
        lines.append(f'QtSignal {parent} LayersTable itemSelectionChanged {row} "{label}"')
        lines.append(f'QtSignal {parent} PadShape CurrentIndexChanged {geom["shape"].title() if geom else "None"}')
        if geom:
            if geom['shape'] == 'circle':
                lines.append(f'QtSignal {parent} PadDiameter editingFinished {fmt(geom["width"])}')
            else:
                lines.append(f'QtSignal {parent} PadWidth editingFinished {fmt(geom["width"])}')
                if geom['shape'] == 'rectangle':
                    lines.append(f'QtSignal {parent} PadHeight editingFinished {fmt(geom["height"])}')
    if not smd:
        d = spec['drill']
        lines += ['QtSignal GuidedTabsParent GuidedTabs currentChanged Drill',
                  'QtSignal GuidedDrillTab Plating CurrentIndexChanged ' + ('Plated' if d['plating'] == 'plated' else 'Non-plated'),
                  f'QtSignal GuidedDrillTab holeXSize editingFinished {fmt(d["diameter"])}',
                  f'QtSignal GuidedDrillTab HolePlusTolerance editingFinished {fmt(d["plus"])}',
                  f'QtSignal GuidedDrillTab HoleMinusTolerance editingFinished {fmt(d["minus"])}',
                  'QtSignal GuidedTabsParent GuidedTabs currentChanged "Drill Symbol"',
                  'QtSignal GuidedDrillSymbol FigureType CurrentIndexChanged Circle',
                  f'QtSignal GuidedDrillSymbol FigureDiameter editingFinished {fmt(d["symbol_diameter"])}']
    lines.append('QtSignal GuidedTabsParent GuidedTabs currentChanged "Design Layers"')
    for row, layer in enumerate(['begin'] if smd else ['begin', 'internal', 'end']):
        emit_geometry('GuidedDesignLayersTab', row, 'Regular Pad', spec['pads'][layer])
    lines.append('QtSignal GuidedTabsParent GuidedTabs currentChanged "Mask Layers"')
    for row, layer in enumerate(['mask_top', 'mask_bottom', 'paste_top', 'paste_bottom']):
        emit_geometry('GuidedMaskLayersTab', row, mask_column, spec['pads'].get(layer))
    lines += ['QtSignal MainWindow SaveAs triggered', f'QtFillin {spec["name"]}.pad',
              'QtSignal MainWindow Exit triggered']
    return '\n'.join(lines) + '\n'


def read_report(path):
    text = path.read_text(errors='replace')
    match = re.search(r'Dimensions in (millimeters|mils) with (\d+) decimal places', text)
    identity = re.search(r'Padstack: (\S+) Type: (\S+)', text)
    if not match or not identity or 'Total Padstack Definitions: 1' not in text:
        raise ValueError('unexpected or incomplete Cadence report')
    rows, drill = {}, None
    raw = list(csv.reader(text.splitlines()))
    for i, row in enumerate(raw):
        if len(row) == 11 and row[1] in ('REGULAR', 'ANTI', 'THERMAL', 'KEEPOUT'):
            key = (row[0], row[1])
            if key in rows:
                raise ValueError('duplicate pad layer in report')
            rows[key] = row
        if row and row[0] == 'Hole Type' and i + 1 < len(raw):
            if len(row) != len(raw[i + 1]):
                raise ValueError('incomplete drill report row')
            drill = dict(zip(row, raw[i + 1]))
    return {'units': match[1], 'accuracy': int(match[2]), 'name': identity[1],
            'type': identity[2], 'rows': rows, 'drill': drill}


def verify(spec, path):
    data = read_report(path)
    if data['name'].casefold() != spec['name'].casefold() or data['units'] != ('millimeters' if spec['units'] == 'mm' else 'mils') or data['accuracy'] != spec['accuracy']:
        raise ValueError('readback name/units/accuracy mismatch')
    if data['type'] != {'smd': 'Surface_pin', 'thru': 'Through_pin', 'mounting': 'Mounting_hole'}[spec['kind']]:
        raise ValueError(f'readback usage mismatch: {data["type"]}')
    expected = {(LAYERS[layer], 'REGULAR'): geom for layer, geom in spec['pads'].items() if geom}
    for key, row in data['rows'].items():
        if row[2] == 'NULL':
            continue
        if key not in expected:
            raise ValueError(f'unexpected non-null layer: {key}')
        geom = expected.pop(key)
        if row[2] != geom['shape'].upper() or any(number(row[i]) != number(geom[k]) for i, k in [(3, 'width'), (4, 'height')]) or any(number(row[i]) != number(geom.get('offset',[0,0])[j]) for j,i in enumerate((5,6))) or any(row[i] for i in (7, 8, 9)) or number(row[10]) != 0:
            raise ValueError(f'readback geometry mismatch: {key}: {row}')
    if expected:
        raise ValueError(f'missing pad layers: {list(expected)}')
    drill = data['drill']
    if not drill:
        raise ValueError('missing drill readback')
    if spec['kind'] == 'smd':
        if drill.get('Hole Type') != 'NONE':
            raise ValueError('unexpected SMD drill')
        for key in ('Slot Size X', 'Slot Size Y', 'Width', 'Height', 'Offset X', 'Offset Y',
                    'Pos Tolerance', 'Neg Tolerance', 'Slot Pos Tolerance', 'Slot Neg Tolerance'):
            if key not in drill or number(drill[key]) != 0:
                raise ValueError('unexpected SMD drill dimensions')
        if drill.get('Figure') != 'NULL' or drill.get('Characters') != '':
            raise ValueError('unexpected SMD drill symbol')
    else:
        d = spec['drill']
        if drill.get('Hole Type') != 'CIRCLE_DRILL' or drill.get('Plating') != ('PLATED' if d['plating'] == 'plated' else 'NON_PLATED'):
            raise ValueError(f'drill kind/plating mismatch: {drill}')
        for key, val in [('Drill Dia', d['diameter']), ('Pos Tolerance', d['plus']),
                         ('Neg Tolerance', d['minus']), ('Offset X', 0), ('Offset Y', 0),
                         ('Width', d['symbol_diameter']), ('Height', d['symbol_diameter'])]:
            if key not in drill or number(drill[key]) != number(val):
                raise ValueError(f'drill dimension mismatch: {drill}')
        if drill.get('Figure') != 'CIRCLE' or drill.get('Characters') != '' or drill.get('Non-Standard') != 'STANDARD':
            raise ValueError('unexpected drill symbol or nonstandard hole')
    return {'geometry_verified': True, 'drill_verified': True}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_process(command, cwd, env, seconds, log, completed_journal=None):
    start = time.monotonic()
    cleanup = False
    ended_at = None
    with log.open('w') as stream:
        proc = subprocess.Popen(command, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        while proc.poll() is None:
            now = time.monotonic()
            if completed_journal and completed_journal.exists():
                journal = completed_journal.read_text(errors='replace')
                if ('padstack_editor 17.2 P19 Linux SPB 64-bit Edition' in journal
                        and 'Journal end' in journal and 'QtSignal MainWindow Exit triggered' in journal):
                    ended_at = ended_at or now
            cleanup = ended_at is not None and now - ended_at >= 2
            if cleanup or now - start >= seconds:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
                break
            time.sleep(0.1)
    elapsed = time.monotonic() - start
    timed_out = not cleanup and elapsed >= seconds
    return {'command': command, 'returncode': proc.returncode, 'timed_out': timed_out,
            'mainwin_exit_cleanup': cleanup, 'seconds': round(elapsed, 2)}


def build(spec, out, args, original=None, transform=None):
    out.mkdir(parents=True, exist_ok=False)
    if original is not None:(out/'input-spec.json').write_text(json.dumps(original,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    if transform:(out/'coordinate-transform.json').write_text(json.dumps(transform,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    (out / 'spec.json').write_text(json.dumps(spec, indent=2, ensure_ascii=False) + '\n',encoding='utf-8')
    has_offsets=any(g and any(number(x)!=0 for x in g.get('offset',[0,0])) for g in spec['pads'].values())
    if not has_offsets:(out / 'build.scr').write_text(replay(spec, args.replay_mask_column),encoding='utf-8')
    elif args.backend!='xml':raise ValueError('Nonzero layer offsets require --backend xml')
    if spec['kind'] == 'smd':
        (out / (spec['name'] + '.pxml')).write_text(pxml(spec),encoding='utf-8')
    result = {'status': 'generated_only', 'verification': None, 'runs': [], 'sources': []}
    try:
        for source in spec['sources']:
            record = dict(source)
            if 'path' in source:
                p = Path(source['path']).expanduser().resolve(strict=True)
                record.update(path=str(p), sha256=digest(p))
            result['sources'].append(record)
        if args.execute:
            if not args.cadence_root:raise ValueError('--cadence-root is required for native execution')
            root = Path(args.cadence_root).resolve(strict=True)
            bindir = root / 'tools.lnx86/bin'
            if args.backend == 'xml' and args.compat_172:
                raise ValueError('17.2 P19 does not support the required XML interface; use replay')
            if not (bindir / 'padstack_editor.exe').is_file():
                raise ValueError('Cadence executable not found under supplied root')
            env = dict(os.environ, CDSROOT=str(root), CDS_AUTO_64BIT='ALL',
                       PATH=str(bindir) + os.pathsep + os.environ.get('PATH', ''),
                       ALLEGRO_MWUSER_DIR=str(out / 'mw'))
            env.pop('DISPLAY', None)
            env.pop('WAYLAND_DISPLAY', None)
            editor = [str(bindir / 'padstack_editor')]
            if args.starter_file:
                if args.compat_172:
                    raise ValueError('--starter-file cannot be combined with --compat-172')
                starter = args.starter_file.resolve(strict=True)
                result['starter'] = {'path': str(starter), 'sha256': digest(starter)}
                editor = [str(starter), str(bindir / 'padstack_editor.exe')]
            if args.compat_172:
                wrapper = Path(__file__).with_name('compat-exec.sh').resolve()
                editor = [str(bindir / 'wstarter'), str(wrapper), str(bindir / 'padstack_editor.exe')]
            if args.display == 'xvfb':
                editor = ['xvfb-run', '-a'] + editor
            if args.backend == 'xml':
                if spec['kind'] != 'smd':
                    raise ValueError('XML backend currently only supports SMD')
                editor += ['-x', spec['name'] + '.pxml']
            else:
                editor += ['-s', 'build.scr']
            run = run_process(editor, out, env, args.timeout, out / 'editor.log',
                              out / 'padstack_editor.jrl' if args.cleanup_mainwin_exit else None)
            result['runs'].append(run)
            journal = out / 'padstack_editor.jrl'
            jtext = journal.read_text(errors='replace') if journal.exists() else ''
            result['editor_binary_sha256'] = digest(bindir / 'padstack_editor.exe')
            result['cadence_version'] = next((line for line in jtext.splitlines() if 'padstack_editor ' in line), None)
            pad = out / (spec['name'] + '.pad')
            # A journal ending is useful evidence but never turns a timeout into a clean exit.
            if not pad.is_file() or not pad.stat().st_size:
                raise ValueError('Cadence produced no nonempty PAD; see editor log/journal')
            result['editor_journal_ended'] = 'Journal end' in jtext
            result['journal_warnings'] = [line for line in jtext.splitlines() if line.startswith('\\w ')]
            if any(line.startswith('\\e ') for line in jtext.splitlines()):
                raise ValueError('Cadence journal contains errors')
            report = out / 'readback.txt'
            rcommand = [str(bindir / 'report'), '-v', 'pad', pad.name, report.name]
            rrun = run_process(rcommand, out, env, args.timeout, out / 'report.log')
            result['runs'].append(rrun)
            if rrun['returncode'] != 0 or rrun['timed_out']:
                raise ValueError('Cadence report failed')
            result['verification'] = verify(spec, report)
            if run['mainwin_exit_cleanup']:
                result['status'] = 'verified_with_exit_cleanup'
            elif run['returncode'] != 0 or run['timed_out']:
                result['status'] = 'verified_geometry_process_failed'
            else:
                result['status'] = 'verified'
    except (ValueError, OSError) as exc:
        result['status'] = 'failed'
        result['error'] = str(exc)
    result['files'] = {str(p.relative_to(out)): {'size': p.stat().st_size, 'sha256': digest(p)}
                       for p in sorted(out.rglob('*')) if p.is_file() and not p.is_symlink()}
    (out / 'result.json').write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n',encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    compile_p = sub.add_parser('build', help='emit replay/pXML and optionally create and verify PAD')
    compile_p.add_argument('spec', type=Path)
    compile_p.add_argument('--out', required=True, type=Path)
    compile_p.add_argument('--execute', action='store_true')
    compile_p.add_argument('--backend', choices=['replay', 'xml'], default='replay')
    compile_p.add_argument('--replay-mask-column', choices=['Pad', 'Regular Pad'], default='Pad', help='Mask table column: Pad for 17.2 P19, Regular Pad for 24.1 S004')
    compile_p.add_argument('--cadence-root', default=None)
    compile_p.add_argument('--display', choices=['none', 'xvfb'], default='none')
    compile_p.add_argument('--compat-172', action='store_true')
    compile_p.add_argument('--starter-file', type=Path, help='explicit audited native launcher taking the editor executable as its first argument')
    compile_p.add_argument('--cleanup-mainwin-exit', action='store_true',
                           help='17.2 only: reclaim process after normal journal end; independent PAD verification remains required')
    compile_p.add_argument('--timeout', type=float, default=30)
    vp = sub.add_parser('verify', help='compare a native Cadence report against a spec')
    vp.add_argument('spec', type=Path)
    vp.add_argument('report', type=Path)
    args = parser.parse_args()
    try:
        original=json.loads(args.spec.read_text(encoding='utf-8'))
        spec,transform=normalize_measurement(original)
        spec=validate(spec)
        if args.command == 'verify':
            result = verify(spec, args.report)
        else:
            if args.cleanup_mainwin_exit and (not args.compat_172 or args.backend != 'replay'):
                raise ValueError('exit cleanup is restricted to the verified 17.2 replay profile')
            if not 1 <= args.timeout <= 300:
                raise ValueError('timeout must be 1..300 seconds')
            result = build(spec, args.out.resolve(), args, original, transform)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result.get('status', 'verified') in ('verified', 'verified_with_exit_cleanup', 'generated_only') else 1
    except (ValueError, OSError, TypeError) as exc:
        print(json.dumps({'status': 'failed', 'error': str(exc)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    sys.exit(main())
