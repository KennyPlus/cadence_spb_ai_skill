#!/usr/bin/env python3
"""Headless Capture Design XML generation, checks and previews; no native execution."""
import argparse
import copy
import hashlib
import html
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET


def require(ok, message):
    if not ok:
        raise ValueError(message)


def exact(value, required, optional=()):
    require(isinstance(value, dict), 'Expected an object')
    require(set(required) <= value.keys(), 'Missing fields: ' + str(set(required) - value.keys()))
    require(value.keys() <= set(required) | set(optional), 'Unknown fields: ' + str(value.keys() - set(required) - set(optional)))


def text(value):
    require(isinstance(value, str) and value.strip() and all(32 <= ord(c) < 0xD800 or 0xE000 <= ord(c) <= 0xFFFD or 0x10000 <= ord(c) <= 0x10FFFF for c in value), 'Expected nonempty XML-safe text')
    return value


def identifier(value):
    require(isinstance(value, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.+-]*', value), 'Invalid identifier: ' + str(value))
    return value


def scalar_name(value):
    require(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_+.-]+', value), 'Invalid scalar name: ' + str(value))
    return value


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'Duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=unique)


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class NoDTD(ET.TreeBuilder):
    def doctype(self, name, public, system):
        raise ValueError('DTD and entities are not supported')


def read_xml(path):
    data = Path(path).read_bytes()
    require(len(data) <= 64 * 1024 * 1024, 'XML exceeds 64 MiB')
    require(not data.startswith(bytes.fromhex('D0CF11E0A1B11AE1')), 'Binary Capture DSN/OLB: use existing exported XML for offline work')
    return ET.fromstring(data, parser=ET.XMLParser(target=NoDTD()))


def definition(element):
    values = element.findall('Defn')
    require(len(values) == 1, 'Expected one Defn in ' + element.tag)
    return values[0].attrib


def obj(parent, tag, **attrs):
    element = ET.SubElement(parent, tag)
    ET.SubElement(element, 'Defn', {k: str(v) for k, v in attrs.items()})
    return element


def libraries(root, profile):
    exact(profile, ['schema', 'basis', 'types'])
    require(type(profile['schema']) is int and profile['schema'] == 1, 'Profile schema must be 1')
    text(profile['basis'])
    kinds = {'INPUT', 'OUTPUT', 'BIDIRECTIONAL', '3STATE', 'PASSIVE', 'OPEN_COLLECTOR', 'OPEN_EMITTER', 'POWER'}
    require(isinstance(profile['types'], dict) and profile['types'], 'Pin type profile required')
    require(all(k in kinds and type(v) is int and 0 <= v <= 255 for k, v in profile['types'].items()), 'Invalid pin type profile')
    inverse = {str(v): k for k, v in profile['types'].items()}
    require(len(inverse) == len(profile['types']), 'Ambiguous pin type profile')
    require(root.tag == 'Lib', 'Expected Capture Library XML')
    result = {}
    for package in root.findall('Package'):
        name = text(definition(package)['name'])
        require(name not in result, 'Duplicate package: ' + name)
        require(definition(package).get('isHomogeneous') == '1', 'Heterogeneous packages are outside the offline model')
        for element in package.iter():
            require(element.tag not in {'PinShared', 'PinSwap', 'ContentsLibName', 'ContentsViewName', 'ContentsViewType'},
                    'Library property is outside the offline model: ' + element.tag)
            if element.tag in {'PackageUserProp', 'SymbolUserProp', 'PinUserProp'}:
                props = definition(element)
                require(element.tag == 'PinUserProp' and props.get('name') in {'AgentElectricalRole', 'AgentEvidence'},
                        'Unmodeled library property: ' + str(props.get('name')))
                text(props.get('val'))
        parts = package.findall('LibPart')
        require(len(parts) == 1, 'Multiple units are outside the offline model: ' + name)
        part = parts[0]
        views, physical = part.findall('NormalView'), part.findall('PhysicalPart')
        require(len(views) == len(physical) == 1 and part.find('ConvertView') is None, 'Unsupported unit or alternate view: ' + name)
        view = views[0]
        require(view.find('SymbolPinBus') is None, 'Bus pins are outside the offline model')
        numbers = {}
        for element in physical[0].findall('PinNumber'):
            d = definition(element)
            require(d['position'] not in numbers, 'Duplicate physical pin position')
            scalar_name(d['number'])
            numbers[d['position']] = d['number']
        require(len({n.casefold() for n in numbers.values()}) == len(numbers), 'Stacked physical numbers are unsupported')
        pins = {}
        for element in view.findall('SymbolPinScalar'):
            d = definition(element); position = d['position']
            require(position in numbers and numbers[position] not in pins, 'Missing/duplicate physical pin mapping')
            require(d['visible'] == '1', 'Hidden pins are outside the offline model')
            global_flag = element.find('IsGlobal/Defn')
            require(global_flag is not None and global_flag.get('val') == '0', 'Implicit/global pins are unsupported')
            require(d['type'] in inverse, 'Pin type missing from evidenced profile: ' + d['type'])
            nc = element.find('IsNoConnect/Defn')
            require(nc is None or nc.get('val') in {'0', '1'}, 'Invalid library NC flag')
            pins[numbers[position]] = {'name': text(d['name']), 'xy': [int(d['hotptX']), int(d['hotptY'])],
                                       'type': inverse[d['type']], 'nc': nc is not None and nc.get('val') == '1',
                                       'position': position, 'element': element}
        require(pins and set(pins) == set(numbers.values()), 'Incomplete physical pin mapping')
        bbox = view.find('SymbolBBox')
        require(bbox is not None, 'Symbol bounding box required')
        bounds = definition(bbox)
        bounds = [int(bounds[k]) for k in ('x1', 'y1', 'x2', 'y2')]
        require(bounds[0] < bounds[2] and bounds[1] < bounds[3], 'Invalid symbol bounds')
        result[name] = {'pins': pins, 'bounds': bounds, 'element': package,
                        'graphic': definition(part).get('CellName', name) + definition(view)['suffix']}
    require(result, 'No library packages')
    return result


def point(value, grid):
    require(isinstance(value, list) and len(value) == 2 and all(type(x) is int and abs(x) <= 100000 for x in value), 'Expected bounded integer Capture coordinates')
    require(all(x % grid == 0 for x in value), 'Coordinate is off the declared grid')
    return tuple(value)


def on_segment(p, a, b):
    return ((b[0] - a[0]) * (p[1] - a[1]) == (b[1] - a[1]) * (p[0] - a[0]) and
            min(a[0], b[0]) <= p[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= p[1] <= max(a[1], b[1]))


def intersections(a, b, c, d):
    points = {p for p in (a, b, c, d) if on_segment(p, a, b) and on_segment(p, c, d)}
    if a[0] == b[0] and c[1] == d[1]:
        p = (a[0], c[1])
        if on_segment(p, a, b) and on_segment(p, c, d): points.add(p)
    if a[1] == b[1] and c[0] == d[0]:
        p = (c[0], a[1])
        if on_segment(p, a, b) and on_segment(p, c, d): points.add(p)
    return points


def check(plan, library, profile):
    exact(plan, ['schema', 'name', 'root', 'units', 'grid', 'sources', 'pages', 'parts', 'nets'])
    require(type(plan['schema']) is int and plan['schema'] == 1 and plan['units'] == 'capture_db', 'Expected schema 1 and capture_db units')
    identifier(plan['name']); identifier(plan['root'])
    require(type(plan['grid']) is int and 1 <= plan['grid'] <= 1000, 'Invalid grid')
    require(isinstance(plan['sources'], list) and plan['sources'], 'Engineering evidence required')
    for source in plan['sources']:
        exact(source, ['location', 'basis']); text(source['location']); text(source['basis'])
    catalog = libraries(library, profile); grid = plan['grid']; pages = {}; parts = {}; pins = {}; nets = {}; assigned = {}
    for key in ('pages', 'parts', 'nets'):
        require(isinstance(plan[key], list) and plan[key], key + ' must be a nonempty list')
    for page in plan['pages']:
        exact(page, ['name', 'size']); identifier(page['name']); size = point(page['size'], grid)
        require(min(size) > 0 and page['name'].casefold() not in pages, 'Invalid/duplicate page')
        pages[page['name'].casefold()] = page
    def in_page(page, xy):
        require(page.casefold() in pages, 'Unknown page: ' + page)
        size = pages[page.casefold()]['size']
        require(all(0 <= x <= limit for x, limit in zip(xy, size)), 'Geometry outside page: ' + page)
    for part in plan['parts']:
        exact(part, ['refdes', 'package', 'page', 'at', 'value', 'footprint', 'basis', 'no_connect'])
        ref = part['refdes']; require(isinstance(ref, str) and re.fullmatch(r'[A-Z]+[0-9]+', ref), 'Annotated uppercase reference required')
        require(ref not in parts and part['package'] in catalog, 'Duplicate reference or unknown package: ' + ref)
        text(part['value']); scalar_name(part['footprint']); text(part['basis']); text(part['page'])
        at = point(part['at'], grid); in_page(part['page'], at)
        require(part['page'] == pages[part['page'].casefold()]['name'], 'Page name case mismatch')
        parts[ref] = part
        package = catalog[part['package']]
        for number, pin in package['pins'].items():
            xy = tuple(at[i] + pin['xy'][i] for i in range(2)); point(list(xy), grid); in_page(part['page'], xy)
            pins[(ref, number)] = dict(pin, xy=xy, page=part['page'])
        for xy in (package['bounds'][:2], package['bounds'][2:]):
            in_page(part['page'], tuple(at[i] + xy[i] for i in range(2)))
        require(isinstance(part['no_connect'], list), 'no_connect must be a list')
        for nc in part['no_connect']:
            exact(nc, ['pin', 'basis']); text(nc['basis']); key = (ref, text(nc['pin']))
            require(key in pins and key not in assigned, 'Invalid/duplicate NC pin')
            assigned[key] = None
    used_points = {}
    for key, pin in pins.items():
        pos = (pin['page'], pin['xy'])
        require(pos not in used_points, 'Overlapping physical pins')
        used_points[pos] = key
    diagnostics = []; all_segments = []
    def finding(severity, code, subject, message):
        diagnostics.append(dict(severity=severity, code=code, subject=subject, message=message))
    for i, a in enumerate(plan['parts']):
        ba = [v + a['at'][j % 2] for j, v in enumerate(catalog[a['package']]['bounds'])]
        for b in plan['parts'][i + 1:]:
            bb = [v + b['at'][j % 2] for j, v in enumerate(catalog[b['package']]['bounds'])]
            if a['page'] == b['page'] and max(ba[0], bb[0]) < min(ba[2], bb[2]) and max(ba[1], bb[1]) < min(ba[3], bb[3]):
                finding('error', 'symbol_overlap', a['refdes'] + '/' + b['refdes'], 'Symbol bodies overlap')
    for net in plan['nets']:
        exact(net, ['name', 'page', 'nodes', 'wires', 'basis']); name = scalar_name(net['name']); text(net['basis']); text(net['page'])
        require(name.casefold() not in nets, 'Duplicate net name; cross-page connectivity is outside the offline model')
        require(net['page'].casefold() in pages and pages[net['page'].casefold()]['name'] == net['page'], 'Unknown/case-mismatched net page')
        nets[name.casefold()] = net
        require(isinstance(net['nodes'], list) and len(net['nodes']) >= 2, 'Each net requires at least two physical nodes')
        nodes = []
        for node in net['nodes']:
            require(isinstance(node, list) and len(node) == 2 and all(isinstance(x, str) for x in node), 'Node must be [refdes,pin]')
            key = tuple(node)
            require(key in pins and key not in assigned, 'Unknown, duplicate, NC, or multiply assigned node: ' + str(key))
            require(pins[key]['page'] == net['page'], 'Cross-page wire is outside the offline model')
            require(not pins[key]['nc'], 'Library NC pin cannot be connected')
            assigned[key] = name; nodes.append(pins[key]['xy'])
        require(isinstance(net['wires'], list) and net['wires'], 'Explicit wire segments required')
        segments = []
        for wire in net['wires']:
            require(isinstance(wire, list) and len(wire) == 2, 'Wire must be [[x1,y1],[x2,y2]]')
            a, b = (point(v, grid) for v in wire)
            require(a != b and (a[0] == b[0] or a[1] == b[1]), 'Wire must be nonzero and orthogonal')
            in_page(net['page'], a); in_page(net['page'], b)
            require((a, b) not in segments and (b, a) not in segments, 'Duplicate wire')
            segments.append((a, b)); all_segments.append((net['page'], name, a, b))
        # All crossings within one net become explicit junctions in generated XML.
        vertices = set(nodes) | {p for edge in segments for p in edge}
        for i, (a, b) in enumerate(segments):
            for c, d in segments[i + 1:]:
                contact = intersections(a, b, c, d)
                require(len(contact) < 2, 'Overlapping collinear wires')
                vertices.update(contact)
        graph = {p: set() for p in vertices}
        for a, b in segments:
            chain = sorted(p for p in vertices if on_segment(p, a, b))
            for x, y in zip(chain, chain[1:]): graph[x].add(y); graph[y].add(x)
        reached = set(); stack = [nodes[0]]
        while stack:
            p = stack.pop()
            if p not in reached: reached.add(p); stack.extend(graph[p] - reached)
        if reached != vertices: finding('error', 'disconnected_wire', name, 'Declared nodes and wire segments are not one connected graph')
        if any(len(neighbors) == 1 and p not in nodes for p, neighbors in graph.items()):
            finding('error', 'dangling_wire', name, 'Wire endpoint has no pin or continuation')
        types = [pins[tuple(n)]['type'] for n in net['nodes']]
        if types.count('OUTPUT') > 1: finding('error', 'multiple_outputs', name, 'Multiple push-pull outputs share one net')
        if 'INPUT' in types and not any(t in {'OUTPUT', 'BIDIRECTIONAL', '3STATE', 'OPEN_COLLECTOR', 'OPEN_EMITTER', 'POWER'} for t in types):
            finding('warning', 'input_without_driver', name, 'Review the driver or external-source evidence')
        if any(t in {'3STATE', 'OPEN_COLLECTOR', 'OPEN_EMITTER'} for t in types):
            finding('warning', 'conditional_driver', name, 'Review pull resistors and driver enables')
    require(set(assigned) == set(pins), 'Every physical pin must be wired or explicitly NC: ' + str(sorted(set(pins) - set(assigned))))
    for i, (page, name, a, b) in enumerate(all_segments):
        for key, pin in pins.items():
            if pin['page'] == page and on_segment(pin['xy'], a, b) and assigned[key] != name:
                finding('error', 'unintended_pin_contact', name, 'Wire touches a pin assigned elsewhere: ' + '.'.join(key))
        for other_page, other_name, c, d in all_segments[i + 1:]:
            if page == other_page and name != other_name and intersections(a, b, c, d):
                finding('error', 'net_contact', name + '/' + other_name, 'Distinct nets touch or cross; reroute explicitly')
    return {'status': 'model_errors' if any(d['severity'] == 'error' for d in diagnostics) else 'checked_model',
            'native_capture_verified': False, 'component_count': len(parts), 'physical_pin_count': len(pins),
            'net_count': len(nets), 'diagnostics': diagnostics}, catalog


def design_xml(plan, library, catalog, template):
    require(template.tag == 'Design', 'Expected an empty Capture Design XML template')
    root_def = definition(template)
    require('objectType' in root_def and 'rootName' in root_def, 'Incomplete Design XML template metadata')
    require(len(template.findall('Schematic')) == 1, 'Template must have one flat schematic')
    pages = template.findall('Schematic/Page')
    require(len(pages) == 1, 'Template must have one empty page')
    # Only known inert metadata is accepted in the seed. Do not drop hidden topology.
    require(set(e.tag for e in template) <= {'Defn', 'DefaultValues', 'Cache', 'Schematic'}, 'Unsupported design template object')
    require(len(template.findall('Cache')) <= 1 and len(template.findall('DefaultValues')) <= 1, 'Duplicate template metadata/cache')
    defaults = template.find('DefaultValues')
    if defaults is not None:
        require(set(e.tag for e in defaults) <= {'Defn', 'DefaultFont', 'DefaultPageRec', 'DefaultPlacedInstIsPrimitive'}, 'Unsupported template defaults')
        require(len(defaults.findall('DefaultPlacedInstIsPrimitive')) <= 1, 'Duplicate primitive default')
        for element in defaults.findall('DefaultPlacedInstIsPrimitive'):
            require(definition(element).get('val') == '1', 'Template must not default to non-primitive instances')
    require(set(e.tag for e in template.find('Schematic')) <= {'Defn', 'Page'}, 'Unsupported schematic template object')
    require(set(e.tag for e in pages[0]) <= {'Defn', 'PageSizeInfo', 'PageSize', 'PageNumber', 'TitleblockDisplayed', 'BorderDisplayed', 'GridRefDisplayed'}, 'Template page is not empty or has unsupported objects')
    cache = template.find('Cache')
    require(cache is None or all(e.tag == 'Defn' for e in cache), 'Template cache must be empty')
    result = copy.deepcopy(template); definition(result).update(name=plan['name'] + '.dsn', rootName=plan['root'])
    cache = result.find('Cache')
    if cache is None: cache = obj(result, 'Cache')
    for name in sorted({p['package'] for p in plan['parts']}):
        package = copy.deepcopy(catalog[name]['element'])
        definition(package)['sourceLibName'] = definition(library)['name']
        cache.append(package)
    schematic = result.find('Schematic'); definition(schematic)['name'] = plan['root']
    for page in schematic.findall('Page'): schematic.remove(page)
    for page_plan in plan['pages']:
        page = copy.deepcopy(pages[0]); definition(page)['name'] = page_plan['name']; schematic.append(page)
        size = page.find('PageSizeInfo')
        require(size is not None, 'Template must declare native PageSizeInfo')
        definition(size).update(width=str(page_plan['size'][0]), height=str(page_plan['size'][1]))
        for p in (p for p in plan['parts'] if p['page'] == page_plan['name']):
            package = catalog[p['package']]
            inst = obj(page, 'PartInst', name='I_' + p['refdes'], pkgName=p['package'],
                       libName=definition(library)['name'], deviceDesignator='', locX=p['at'][0], locY=p['at'][1], rotation=0, mirror=0)
            obj(inst, 'GraphicName', name=package['graphic'])
            obj(inst, 'Reference', name=p['refdes']); obj(inst, 'PartValue', name=p['value'])
            obj(inst, 'PartInstUserProp', name='PCB Footprint', val=p['footprint'])
            for nc in p['no_connect']:
                pin = package['pins'][nc['pin']]; d = definition(pin['element'])
                port = obj(inst, 'PortInstScalar', name=d['name'], hotptX=d['hotptX'], hotptY=d['hotptY'],
                           startX=d['startX'], startY=d['startY'], type=d['type'], visible=1, IsPlacedInstPin=1, position=d['position'])
                obj(port, 'IsNoConnect', val=1)
        for net in (n for n in plan['nets'] if n['page'] == page_plan['name']):
            for a, b in net['wires']:
                wire = obj(page, 'WireScalar', name=net['name'], startX=a[0], startY=a[1], endX=b[0], endY=b[1])
                obj(wire, 'Alias', name=net['name'], locX=a[0], locY=a[1], rotation=0, color=0)
                junctions = set()
                for c, d in net['wires']:
                    if [a, b] != [c, d]: junctions.update(intersections(tuple(a), tuple(b), tuple(c), tuple(d)))
                for x, y in sorted(junctions): obj(wire, 'Junction', locX=x, locY=y)
    ET.indent(result)
    return result


def expected_netlist(plan, catalog):
    return {'schema': 1, 'origin': 'checked_schematic_model', 'native_capture_verified': False,
            'components': {p['refdes']: {'symbol': p['footprint'], 'value': p['value'], 'pins': sorted(catalog[p['package']]['pins'])} for p in plan['parts']},
            'nets': {n['name']: {'nodes': [{'refdes': ref, 'pin': pin} for ref, pin in n['nodes']]} for n in plan['nets']}}


def pst(plan, catalog):
    def quote(value): return "'" + str(value).replace("'", "''") + "'"
    chip = ['FILE_TYPE=LIBRARY_PARTS;', '{ Generated from a checked model, not a native Capture export. }']
    parts = ['FILE_TYPE=EXPANDEDPARTLIST;', 'DIRECTIVES', "PST_VERSION='PST_HDL_CENTRIC_VERSION_0';", 'ROOT_DRAWING=' + quote(plan['root']) + ';', "SOURCE_TOOL='AGENT_SCHEMATIC_MODEL';", 'END_DIRECTIVES;']
    nets = ['FILE_TYPE=EXPANDEDNETLIST;']
    paths = {}
    for p in plan['parts']:
        ref = p['refdes']; device = 'MODEL_' + ref; path = '@' + plan['root'] + '.' + p['page'] + ':' + ref; paths[ref] = path
        chip += ['primitive ' + quote(device) + ';', 'pin']
        for pin in catalog[p['package']]['pins']:
            chip.append(quote('PIN_' + pin) + ': PIN_NUMBER=' + quote('(' + pin + ')') + "; PINUSE='UNSPEC';")
        chip += ['end_pin;', 'body', 'PART_NAME=' + quote(p['package']) + '; JEDEC_TYPE=' + quote(p['footprint']) + '; VALUE=' + quote(p['value']) + ';', 'end_body;', 'end_primitive;']
        parts += ['PART_NAME ' + ref + ' ' + quote(device) + ':;', 'SECTION_NUMBER 1 ' + quote(path) + ': C_PATH=' + quote('@' + plan['root'] + '.' + p['page']) + ';']
    for n in plan['nets']:
        nets.append('NET_NAME ' + quote(n['name']) + ' ' + quote('@' + plan['root'] + '.' + n['page']) + ': C_SIGNAL=' + quote(n['name']) + ';')
        for ref, pin in n['nodes']: nets.append('NODE_NAME ' + ref + ' ' + pin + ' ' + quote(paths[ref]) + ': ' + quote('PIN_' + pin) + ':;')
    return {name: '\n'.join(lines + ['END.', '']) for name, lines in zip(('pstchip.dat', 'pstxprt.dat', 'pstxnet.dat'), (chip, parts, nets))}


def svg(plan, catalog, page):
    esc = lambda value: html.escape(str(value), quote=True)
    w, h = page['size']; out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}">', '<rect width="100%" height="100%" fill="white"/>', '<g font-family="sans-serif" font-size="12">']
    for net in (n for n in plan['nets'] if n['page'] == page['name']):
        for a, b in net['wires']: out.append(f'<path d="M {a[0]} {a[1]} L {b[0]} {b[1]}" stroke="#146b45" fill="none"/>')
        junctions = set()
        for i, (a, b) in enumerate(net['wires']):
            for c, d in net['wires'][i + 1:]: junctions.update(intersections(tuple(a), tuple(b), tuple(c), tuple(d)))
        for x, y in sorted(junctions): out.append(f'<circle cx="{x}" cy="{y}" r="3" fill="#146b45"/>')
        a, b = net['wires'][0]
        label_x = (a[0] + b[0]) / 2 + (8 if a[0] == b[0] else 0)
        label_y = (a[1] + b[1]) / 2 - 8
        out.append(f'<text x="{label_x}" y="{label_y}" fill="#146b45">{esc(net["name"])}</text>')
    for p in (p for p in plan['parts'] if p['page'] == page['name']):
        x, y = p['at']; package = catalog[p['package']]; x1, y1, x2, y2 = package['bounds']
        out.append(f'<rect x="{x+x1}" y="{y+y1}" width="{x2-x1}" height="{y2-y1}" fill="white" stroke="#333"/>')
        out.append(f'<text x="{x+x1}" y="{y+y1-10}">{esc(p["refdes"])} {esc(p["value"])}</text>')
        for number, pin in package['pins'].items():
            d = definition(pin['element']); px, py = [x+pin['xy'][0], y+pin['xy'][1]]
            out.append(f'<path d="M {px} {py} L {x+int(d["startX"])} {y+int(d["startY"])}" stroke="#333"/><text x="{px+3}" y="{py-3}">{esc(number)}</text>')
            if any(nc['pin'] == number for nc in p['no_connect']): out.append(f'<path d="M {px-4} {py-4} l 8 8 m -8 0 l 8 -8" stroke="#c00"/>')
    return '\n'.join(out + ['</g></svg>'])


def xml_record(element, children=(), attributes=None):
    require(not element.attrib and not (element.text or '').strip(), 'Unexpected XML content in ' + element.tag)
    require(set(e.tag for e in element) <= {'Defn'} | set(children), 'Unsupported XML object inside ' + element.tag)
    d = definition(element)
    require(not len(element.find('Defn')) and not (element.find('Defn').text or '').strip(), 'Invalid XML Defn in ' + element.tag)
    if attributes is not None:
        require(d.keys() <= set(attributes), 'Unsupported XML attributes in ' + element.tag + ': ' + str(d.keys() - set(attributes)))
    return d


def single(parent, tag):
    elements = parent.findall(tag)
    require(len(elements) == 1, 'Expected one ' + tag + ' in ' + parent.tag)
    return elements[0]


def checked_xml(root, profile, grid):
    """Reconstruct the supported flat model from XML, including its actual cache/wires."""
    require(type(grid) is int and 1 <= grid <= 1000, 'Invalid grid')
    require(root.tag == 'Design', 'Expected Capture Design XML')
    d = xml_record(root, {'DefaultValues', 'Cache', 'Schematic'}, {'name', 'rootName', 'objectType'})
    require(d.get('objectType') == 'SCHEMATIC', 'Expected a schematic Design XML')
    schematic = single(root, 'Schematic')
    sd = xml_record(schematic, {'Page'}, {'name'})
    require(sd['name'] == d['rootName'], 'Root schematic mismatch')
    require(len(root.findall('DefaultValues')) <= 1, 'Duplicate defaults')
    for defaults in root.findall('DefaultValues'):
        xml_record(defaults, {'DefaultFont', 'DefaultPageRec', 'DefaultPlacedInstIsPrimitive'})
        require(len(defaults.findall('DefaultPlacedInstIsPrimitive')) <= 1, 'Duplicate primitive default')
        for primitive in defaults.findall('DefaultPlacedInstIsPrimitive'):
            require(xml_record(primitive, attributes={'val'}).get('val') == '1', 'Non-primitive defaults are unsupported')
    cache = single(root, 'Cache'); xml_record(cache, {'Package'})
    library = ET.Element('Lib'); ET.SubElement(library, 'Defn', name='XML_CACHE')
    for package in cache.findall('Package'):
        xml_record(package, {'PackageAlias', 'LibPart', 'PackageUserProp'})
        part = single(package, 'LibPart'); xml_record(part, {'NormalView', 'PhysicalPart'})
        physical = single(part, 'PhysicalPart'); xml_record(physical, {'PinNumber'})
        for number in physical.findall('PinNumber'): xml_record(number, attributes={'number', 'position'})
        view = single(part, 'NormalView')
        xml_record(view, {'SymbolColor', 'SymbolBBox', 'IsPinNumbersVisible', 'IsPinNamesRotated', 'IsPinNamesVisible',
                          'PartValue', 'Reference', 'Bitmap', 'SymbolPinScalar', 'SymbolDisplayProp', 'Line', 'Ellipse',
                          'Polygon', 'SymbolVector', 'Bezier', 'Arc', 'Polyline', 'CommentText', 'Rect'})
        single(view, 'SymbolBBox')
        flags = {'IsLong', 'IsClock', 'IsDot', 'IsLeftPointing', 'IsRightPointing', 'IsNetStyle', 'IsNoConnect', 'IsGlobal', 'IsNumberVisible'}
        for pin in view.findall('SymbolPinScalar'):
            p = xml_record(pin, flags | {'PinDisplayProp', 'PinUserProp'}, {'name', 'position', 'hotptX', 'hotptY', 'startX', 'startY', 'type', 'visible'})
            for k in ('hotptX', 'hotptY', 'startX', 'startY'):
                require(abs(int(p[k])) <= 100000, 'Invalid cached pin geometry')
            for flag in flags:
                require(len(pin.findall(flag)) <= 1, 'Duplicate XML pin flag: ' + flag)
                for element in pin.findall(flag):
                    require(xml_record(element, attributes={'val'}).get('val') in {'0', '1'}, 'Invalid XML pin flag: ' + flag)
        library.append(copy.deepcopy(package))
    catalog = libraries(library, profile)
    plan = {'schema': 1, 'name': Path(d['name'].replace('\\', '/')).stem, 'root': d['rootName'],
            'units': 'capture_db', 'grid': grid, 'sources': [{'location': 'Design XML', 'basis': 'Read from XML; engineering intent still requires review.'}],
            'pages': [], 'parts': [], 'nets': []}
    instances = set(); groups = {}; junctions = {}; pins = []
    metadata = {'PageSizeInfo', 'PageSize', 'PageNumber', 'TitleblockDisplayed', 'BorderDisplayed', 'GridRefDisplayed'}
    for page in schematic.findall('Page'):
        pd = xml_record(page, metadata | {'PartInst', 'WireScalar'}, {'name'})
        for tag in metadata: require(len(page.findall(tag)) <= 1, 'Duplicate page metadata: ' + tag)
        size = xml_record(single(page, 'PageSizeInfo'), attributes={'width', 'height', 'IsMetric', 'PinToPin'})
        plan['pages'].append({'name': pd['name'], 'size': [int(size['width']), int(size['height'])]})
        for inst in page.findall('PartInst'):
            attrs = xml_record(inst, {'GraphicName', 'Reference', 'PartValue', 'PartInstUserProp', 'PortInstScalar'},
                               {'name', 'pkgName', 'libName', 'deviceDesignator', 'locX', 'locY', 'rotation', 'mirror'})
            require(text(attrs['name']).casefold() not in instances, 'Duplicate XML instance name')
            instances.add(attrs['name'].casefold())
            require(attrs.get('rotation') == '0' and attrs.get('mirror') == '0' and attrs.get('deviceDesignator') == '', 'Unsupported instance rotation, mirror or unit')
            require(attrs['pkgName'] in catalog, 'Missing cached package: ' + attrs['pkgName'])
            package = catalog[attrs['pkgName']]
            require(attrs['libName'] == definition(package['element']).get('sourceLibName'), 'Instance library does not match its cache')
            graphic = xml_record(single(inst, 'GraphicName'), attributes={'name'})
            require(graphic['name'] == package['graphic'], 'Instance graphic does not match its cache')
            ref = xml_record(single(inst, 'Reference'), attributes={'name'})['name']
            value = xml_record(single(inst, 'PartValue'), attributes={'name'})['name']
            prop = xml_record(single(inst, 'PartInstUserProp'), attributes={'name', 'val'})
            require(prop['name'] == 'PCB Footprint', 'Only PCB Footprint instance properties are supported')
            part = {'refdes': ref, 'package': attrs['pkgName'], 'page': pd['name'], 'at': [int(attrs['locX']), int(attrs['locY'])],
                    'value': value, 'footprint': prop['val'], 'basis': 'Read from XML', 'no_connect': []}
            positions = {pin['position']: (number, pin) for number, pin in package['pins'].items()}
            for port in inst.findall('PortInstScalar'):
                p = xml_record(port, {'IsNoConnect'}, {'name', 'position', 'hotptX', 'hotptY', 'startX', 'startY', 'type', 'visible', 'IsPlacedInstPin'})
                require(p.get('position') in positions, 'Unknown instance pin position')
                number, pin = positions[p['position']]; cached = definition(pin['element'])
                require(all(p.get(k) == cached.get(k) for k in ('name', 'position', 'hotptX', 'hotptY', 'startX', 'startY', 'type', 'visible')) and p.get('IsPlacedInstPin') == '1', 'Instance pin override differs from cache')
                require(xml_record(single(port, 'IsNoConnect'), attributes={'val'}).get('val') == '1', 'Only explicit NC pin overrides are supported')
                part['no_connect'].append({'pin': number, 'basis': 'Explicit XML NC marker'})
            plan['parts'].append(part)
            for number, pin in package['pins'].items():
                pins.append((pd['name'], ref, number, tuple(part['at'][i] + pin['xy'][i] for i in range(2))))
        for wire in page.findall('WireScalar'):
            w = xml_record(wire, {'Alias', 'Junction'}, {'name', 'startX', 'startY', 'endX', 'endY'})
            a = point([int(w['startX']), int(w['startY'])], grid); b = point([int(w['endX']), int(w['endY'])], grid)
            alias = xml_record(single(wire, 'Alias'), attributes={'name', 'locX', 'locY', 'rotation', 'color'})
            require(alias['name'] == w['name'], 'Wire name and alias differ')
            require(alias.get('rotation') == '0' and on_segment((int(alias['locX']), int(alias['locY'])), a, b), 'Unsupported or detached net alias')
            key = (pd['name'], scalar_name(alias['name']))
            net = groups.setdefault(key, {'name': key[1], 'page': key[0], 'nodes': [], 'wires': [], 'basis': 'Connectivity inferred from XML wire geometry and cached physical pins'})
            net['wires'].append([list(a), list(b)])
            for junction in wire.findall('Junction'):
                j = xml_record(junction, attributes={'locX', 'locY'}); xy = point([int(j['locX']), int(j['locY'])], grid)
                require(on_segment(xy, a, b), 'Detached XML junction')
                junctions.setdefault(key, set()).add(xy)
    for key, net in groups.items():
        for page, ref, number, xy in pins:
            if page == net['page'] and any(on_segment(xy, *wire) for wire in net['wires']): net['nodes'].append([ref, number])
        for i, (a, b) in enumerate(net['wires']):
            for c, d in net['wires'][i + 1:]:
                for xy in intersections(tuple(a), tuple(b), tuple(c), tuple(d)):
                    if xy not in (tuple(a), tuple(b)) or xy not in (tuple(c), tuple(d)):
                        require(xy in junctions.get(key, set()), 'Missing XML junction at a branch or crossing')
        plan['nets'].append(net)
    result, catalog = check(plan, library, profile)
    result['status'] = 'xml_errors' if result['status'] == 'model_errors' else 'checked_xml'
    result['check_scope'] = 'Flat scalar XML structure, cache references, physical pins, wire geometry and offline electrical rules; not Capture DRC or vendor XSD validation.'
    return result, plan, catalog


def preview_html(plan, catalog, result):
    esc = lambda value: html.escape(str(value), quote=True)
    findings = ''.join('<li>' + esc(d['severity'] + ': ' + d['subject'] + ' — ' + d['message']) + '</li>' for d in result.get('diagnostics', []))
    pages = ''.join('<section><h2>' + esc(page['name']) + '</h2>' + svg(plan, catalog, page) + '</section>' for page in plan['pages'])
    return ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>' + esc(plan['name']) + '</title><style>body{font:16px system-ui;max-width:1200px;margin:32px auto;padding:0 20px;background:#f3f5f7;color:#182431}'
            'section{background:white;padding:16px;margin:24px 0;border:1px solid #c9d3dc;border-radius:8px}svg{width:100%;height:auto}li{margin:8px 0}</style>'
            '<h1>' + esc(plan['name']) + '</h1><p>Offline XML connectivity preview. Symbol bodies are simplified; pin numbers, wires and NC markers come from the checked XML.</p>'
            '<p>Checks: ' + esc(result['status']) + '. Native Capture DRC: not run.</p><ul>' + findings + '</ul>' + pages + '</html>')


def inspect_xml(root):
    require(root.tag == 'Design', 'Expected Capture Design XML, not Library XML or SPECCTRA DSN')
    result = {'status': 'inventory_only', 'native_capture_verified': False, 'design': dict(definition(root)), 'pages': [], 'unsupported_objects': []}
    known = {'Defn', 'PageSizeInfo', 'PageSize', 'PageNumber', 'TitleblockDisplayed', 'BorderDisplayed', 'GridRefDisplayed', 'PartInst', 'WireScalar', 'NetScalar'}
    for schematic in root.findall('Schematic'):
        for page in schematic.findall('Page'):
            row = {'schematic': definition(schematic)['name'], 'name': definition(page)['name'], 'parts': [], 'wires': []}
            for inst in page.findall('PartInst'):
                d = dict(definition(inst))
                ref = inst.find('Reference/Defn'); value = inst.find('PartValue/Defn')
                d['reference'] = None if ref is None else ref.get('name'); d['value'] = None if value is None else value.get('name')
                d['properties'] = [dict(definition(e)) for e in inst.findall('PartInstUserProp')]; row['parts'].append(d)
            for wire in page.findall('WireScalar') + page.findall('NetScalar/WireScalar'):
                row['wires'].append(dict(definition(wire), aliases=[dict(definition(a)) for a in wire.findall('Alias')]))
            result['unsupported_objects'].extend(sorted({e.tag for e in page} - known)); result['pages'].append(row)
    result['unsupported_objects'] = sorted(set(result['unsupported_objects']))
    return result


def verify_netlist(expected, actual):
    require(isinstance(actual, dict) and isinstance(actual.get('components'), dict) and isinstance(actual.get('nets'), dict), 'Expected an allegro-pcb parsed netlist snapshot')
    want = expected['components']; got = actual['components']; require(set(want) == set(got), 'Component set differs')
    for ref, part in want.items():
        other = got[ref]
        require(isinstance(other, dict), 'Invalid component record: ' + ref)
        require(part['symbol'] == other.get('symbol'), 'Footprint differs: ' + ref)
        require(isinstance(other.get('pins'), list) and all(isinstance(p, str) for p in other['pins']) and len(other['pins']) == len(set(other['pins'])) and set(part['pins']) == set(other['pins']), 'Physical pin inventory differs: ' + ref)
    def normalize(nets):
        result = {}; used = set()
        for name, net in nets.items():
            require(isinstance(net, dict) and isinstance(net.get('nodes'), list), 'Invalid net record: ' + str(name))
            nodes = []
            for n in net['nodes']:
                exact(n, ['refdes', 'pin']); pair = (text(n['refdes']), text(n['pin']))
                require(pair not in used, 'Duplicate netlist node'); used.add(pair); nodes.append(pair)
            require(nodes, 'Empty net in readback'); result[name] = sorted(nodes)
        return result
    require(normalize(expected['nets']) == normalize(actual['nets']), 'Pin-to-net connectivity differs')
    return {'status': 'netlist_matches_model', 'native_capture_verified': False, 'component_count': len(want), 'net_count': len(expected['nets'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__); commands = parser.add_subparsers(dest='command', required=True)
    for command in ('check', 'build', 'verify-netlist'):
        p = commands.add_parser(command); p.add_argument('plan', type=Path); p.add_argument('--library', type=Path, required=True); p.add_argument('--profile', type=Path, required=True); p.add_argument('--out', type=Path, required=True)
        if command == 'build': p.add_argument('--template', type=Path, required=True)
        if command == 'verify-netlist': p.add_argument('--actual', type=Path, required=True)
    for command in ('check-xml', 'preview'):
        p = commands.add_parser(command, help='Check the supported flat XML dialect without Capture')
        p.add_argument('xml', type=Path); p.add_argument('--profile', type=Path, required=True)
        p.add_argument('--grid', type=int, default=10); p.add_argument('--out', type=Path, required=True)
    p = commands.add_parser('inspect'); p.add_argument('xml', type=Path); p.add_argument('--out', type=Path, required=True)
    p = commands.add_parser('drc-report'); p.add_argument('report', type=Path); p.add_argument('--encoding', default='utf-8-sig'); p.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        require(not args.out.exists(), 'Output directory must be new')
        files = {}; xml = None; catalog = None; preview_plan = None; preview_catalog = None
        if args.command == 'inspect':
            result = inspect_xml(read_xml(args.xml)); inputs = {'xml': digest(args.xml)}
        elif args.command in ('check-xml', 'preview'):
            result, plan, catalog = checked_xml(read_xml(args.xml), read_json(args.profile), args.grid)
            inputs = {'xml': digest(args.xml), 'profile': digest(args.profile)}
            if args.command == 'preview': preview_plan, preview_catalog = plan, catalog
        elif args.command == 'drc-report':
            data = args.report.read_text(encoding=args.encoding); require(data.strip(), 'Empty DRC report')
            findings = [{'line': i, 'text': line} for i, line in enumerate(data.splitlines(), 1) if re.search(r'\b(?:ERROR|WARNING)\s*\(?\s*ORCAP-\d+', line, re.I)]
            result = {'status': 'report_findings_only', 'native_capture_verified': False, 'completion_verified': False,
                      'findings': findings, 'review_required': 'Review the full report, run completion, scope, settings, and waived markers; no matches does not mean DRC passed.'}
            inputs = {'report': digest(args.report)}
        else:
            plan = read_json(args.plan); library = read_xml(args.library); profile = read_json(args.profile)
            result, catalog = check(plan, library, profile)
            inputs = {key: digest(getattr(args, key)) for key in ('plan', 'library', 'profile')}
            if result['status'] == 'checked_model' and args.command == 'build':
                xml = design_xml(plan, library, catalog, read_xml(args.template)); inputs['template'] = digest(args.template)
                # Check and render the serialized XML, not the input plan's declared nodes.
                result, preview_plan, preview_catalog = checked_xml(ET.fromstring(ET.tostring(xml)), profile, plan['grid'])
                require(result['status'] == 'checked_xml', 'Generated XML has errors')
                verify_netlist(expected_netlist(plan, catalog), expected_netlist(preview_plan, preview_catalog))
                files = pst(preview_plan, preview_catalog)
            if args.command == 'verify-netlist':
                require(result['status'] == 'checked_model', 'Model has errors')
                result = verify_netlist(expected_netlist(plan, catalog), read_json(args.actual)); inputs['actual'] = digest(args.actual)
        result['inputs_sha256'] = inputs
        result['execution'] = 'headless'
        result['native_execution'] = 'not_requested'
        result['pending'] = ['Engineering review of the circuit, component evidence and preview limitations']
        result['native_checks_not_run'] = ['Capture import/save/reopen', 'Capture electrical and physical DRC']
        args.out.mkdir(parents=True, exist_ok=False)
        if catalog is not None:
            write_json(args.out / 'plan.json', plan)
            if args.command in ('check', 'verify-netlist') or result['status'] == 'model_errors':
                for page in plan['pages']: (args.out / (page['name'] + '.svg')).write_text(svg(plan, catalog, page), encoding='utf-8')
        if preview_plan is not None:
            for page in preview_plan['pages']:
                (args.out / (page['name'] + '.svg')).write_text(svg(preview_plan, preview_catalog, page), encoding='utf-8')
            (args.out / 'preview.html').write_text(preview_html(preview_plan, preview_catalog, result), encoding='utf-8')
            result['preview_source'] = 'Design XML'
            result['preview_limitations'] = 'Connectivity view with simplified symbol bodies; not a Capture page rendering.'
        if xml is not None:
            ET.ElementTree(xml).write(args.out / (plan['name'] + '.xml'), encoding='utf-8', xml_declaration=True)
            (args.out / 'model-netlist').mkdir()
            for name, data in files.items(): (args.out / 'model-netlist' / name).write_text(data, encoding='utf-8')
            write_json(args.out / 'expected-netlist.json', expected_netlist(preview_plan, preview_catalog))
        result['outputs_sha256'] = {str(p.relative_to(args.out)): digest(p) for p in sorted(args.out.rglob('*')) if p.is_file()}
        write_json(args.out / 'result.json', result); print(json.dumps(result, indent=2, ensure_ascii=False))
        return 2 if result['status'] in {'model_errors', 'xml_errors'} else 0
    except (ValueError, TypeError, KeyError, OSError, ET.ParseError) as error:
        print(json.dumps({'status': 'failed', 'error': str(error)}, ensure_ascii=False), file=sys.stderr); return 2


if __name__ == '__main__':
    sys.exit(main())
