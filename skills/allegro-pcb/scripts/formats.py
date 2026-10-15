"""Portable, data-only readers for Cadence PST and placement exchange files."""
from decimal import Decimal, InvalidOperation
import csv
import hashlib
import json
from pathlib import Path
import re


UNITS = {'mm': Decimal(1), 'mil': Decimal('0.0254')}
UNIT_NAMES = {'MILLIMETER': 'mm', 'MILLIMETERS': 'mm', 'MILS': 'mil', 'MIL': 'mil'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def exact(value, required, optional=()):
    require(isinstance(value, dict), 'Expected an object')
    require(set(required) <= set(value), 'Missing fields: ' + str(set(required) - set(value)))
    require(set(value) <= set(required) | set(optional), 'Unknown fields: ' + str(set(value) - set(required) - set(optional)))


def text(value):
    require(isinstance(value, str) and value.strip() and all(ord(c) >= 32 for c in value), 'Expected nonempty text without control characters')
    return value


def number(value, accuracy=None):
    require(type(value) in (str, int, float, Decimal), 'Expected a numeric dimension')
    try:
        result = Decimal(str(value))
        require(result.is_finite() and abs(result) <= Decimal('1000000'), 'Non-finite or excessive dimension')
        if accuracy is not None:
            require(type(accuracy) is int and 0 <= accuracy <= 6, 'Accuracy must be 0..6')
            require(result == result.quantize(Decimal(1).scaleb(-accuracy)), 'Dimension loses precision at declared accuracy')
        return result
    except InvalidOperation as error:
        raise ValueError('Invalid dimension') from error


def fmt(value):
    return format(number(value), 'f')


def angle(value):
    return (number(value) % 360 + 360) % 360


def point(value, accuracy=None):
    require(isinstance(value, list) and len(value) == 2, 'Point must be [x,y]')
    return [number(v, accuracy) for v in value]


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'Duplicate JSON field: ' + key)
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=unique)


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False,
                                    default=lambda v: fmt(v) if isinstance(v, Decimal) else str(v)) + '\n', encoding='utf-8')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_netlist(value):
    require(isinstance(value, dict) and type(value.get('schema')) is int and value['schema'] == 1,
            'Expected a schema 1 netlist snapshot')
    components, nets = value.get('components'), value.get('nets')
    require(isinstance(components, dict) and components and isinstance(nets, dict), 'Invalid netlist components/nets')
    for refdes, component in components.items():
        require(text(refdes) == refdes.upper() and isinstance(component, dict), 'Invalid netlist component')
        text(component.get('symbol'))
        pins = component.get('pins')
        require(isinstance(pins, list) and pins and all(isinstance(p, str) and p for p in pins), 'Invalid physical pins')
        require(len(set(pins)) == len(pins), 'Duplicate physical pin')
    assigned = set()
    for name, net in nets.items():
        text(name)
        require(isinstance(net, dict) and isinstance(net.get('nodes'), list) and net['nodes'], 'Invalid net nodes')
        for node in net['nodes']:
            exact(node, ['refdes', 'pin'])
            refdes, pin = text(node['refdes']), text(node['pin'])
            require(refdes in components and pin in components[refdes]['pins'], 'Unknown physical node')
            require((refdes, pin) not in assigned, 'Duplicate physical node')
            assigned.add((refdes, pin))


def tokens(data):
    """Tokenize PST, retaining quoted strings and never evaluating source text."""
    pattern = re.compile(r"\s+|\{[^}]*\}|'(?:''|[^'])*'|[;:=,()]|[^\s{}';:=,()]+", re.S)
    result = []
    end = 0
    for match in pattern.finditer(data):
        require(match.start() == end, 'Malformed PST near byte ' + str(end))
        end = match.end()
        value = match.group()
        if value.isspace() or value.startswith('{'):
            continue
        quoted = value.startswith("'")
        result.append((value[1:-1].replace("''", "'") if quoted else value, quoted))
    require(end == len(data), 'Truncated PST token')
    return result


def is_word(token, value):
    return not token[1] and token[0].upper() == value.upper()


def sections(items, keyword):
    starts = [i for i, token in enumerate(items) if is_word(token, keyword)]
    return [items[start + 1:end] for start, end in zip(starts, starts[1:] + [len(items)])]


def properties(items):
    result = {}
    for i in range(len(items) - 2):
        if items[i + 1] == ('=', False):
            key, value = items[i][0].upper(), items[i + 2][0]
            # Section-level metadata may repeat. Preserve every value.
            if key in result and result[key] != value:
                old = result[key]
                result[key] = old + [value] if isinstance(old, list) else [old, value]
            else:
                result[key] = value
    return result


def read_netlist(directory, encoding='utf-8-sig'):
    directory = Path(directory)
    names = ('pstchip.dat', 'pstxprt.dat', 'pstxnet.dat')
    streams, sources = {}, {}
    for name in names:
        path = directory / name
        require(path.is_file(), 'Missing netlist input: ' + name)
        data = path.read_text(encoding=encoding)
        streams[name] = tokens(data)
        require(streams[name] and is_word(streams[name][-1], 'END.') and
                sum(is_word(t, 'END.') for t in streams[name]) == 1,
                'Missing or misplaced END. in ' + name)
        sources[name] = digest(path)
    kinds = ('LIBRARY_PARTS', 'EXPANDEDPARTLIST', 'EXPANDEDNETLIST')
    for name, kind in zip(names, kinds):
        require(properties(streams[name]).get('FILE_TYPE') == kind, 'Unexpected FILE_TYPE in ' + name)
    devices = {}
    for block in sections(streams['pstchip.dat'], 'primitive'):
        require(block and block[0][1], 'Primitive name must be quoted')
        name = block[0][0]
        require(name not in devices, 'Duplicate primitive: ' + name)
        boundaries = {}
        for keyword in ('pin', 'end_pin', 'body', 'end_body', 'end_primitive'):
            positions = [i for i, item in enumerate(block) if is_word(item, keyword)]
            require(len(positions) == 1, 'Missing/duplicate ' + keyword + ' in ' + name)
            boundaries[keyword] = positions[0]
        require(list(boundaries.values()) == sorted(boundaries.values()), 'Malformed primitive block order: ' + name)
        body = sections(block, 'body')
        require(len(body) == 1, 'Primitive needs one body: ' + name)
        attrs = properties(body[0])
        symbol = text(attrs.get('JEDEC_TYPE'))
        pin_blocks = sections(block, 'pin')
        require(len(pin_blocks) == 1, 'Primitive needs a pin block: ' + name)
        pin_items = pin_blocks[0]
        ends = [i for i, item in enumerate(pin_items) if is_word(item, 'end_pin')]
        require(len(ends) == 1, 'Unterminated pin block: ' + name)
        pin_items = pin_items[:ends[0]]
        starts = [i for i in range(len(pin_items) - 1) if pin_items[i][1] and pin_items[i + 1] == (':', False)]
        pins = {}
        for start, end in zip(starts, starts[1:] + [len(pin_items)]):
            pin_attrs = properties(pin_items[start + 2:end])
            value = pin_attrs.get('PIN_NUMBER', '')
            require(isinstance(value, str) and re.fullmatch(r'\([^()]+\)', value), 'Unsupported PIN_NUMBER in ' + name)
            physical = re.split(r'[\s,]+', value[1:-1].strip())
            require(all(re.fullmatch(r'[A-Za-z0-9_+.-]+', v) for v in physical), 'Invalid physical pin number')
            alias = pin_items[start][0]
            require(alias not in pins, 'Duplicate logical pin: ' + alias)
            pins[alias] = {'numbers': physical, 'properties': pin_attrs}
        require(pins, 'No physical pins in ' + name)
        devices[name] = {'symbol': symbol, 'properties': attrs, 'pins': pins}
    components, instance_owners = {}, {}
    for block in sections(streams['pstxprt.dat'], 'PART_NAME'):
        require(len(block) >= 2 and block[1][0] in devices, 'Unknown device in PART_NAME')
        refdes, device = block[0][0].upper(), block[1][0]
        require(refdes not in components, 'Duplicate component: ' + refdes)
        instances = []
        for section in sections(block, 'SECTION_NUMBER'):
            require(len(section) >= 2 and section[1][1], 'Missing component instance path: ' + refdes)
            path = text(section[1][0])
            require(path not in instance_owners or instance_owners[path] == refdes,
                    'Instance path belongs to multiple components: ' + path)
            instance_owners[path] = refdes
            instances.append({'number': section[0][0], 'path': path})
        require(instances, 'Missing SECTION_NUMBER in ' + refdes)
        definition = devices[device]
        components[refdes] = {'device': device, 'symbol': definition['symbol'],
                              'sections': instances,
                              'properties': properties(block[2:]),
                              'pins': sorted({p for v in definition['pins'].values() for p in v['numbers']})}
    require(components, 'Empty component list')
    nets, assigned = {}, {}
    for block in sections(streams['pstxnet.dat'], 'NET_NAME'):
        require(block and block[0][1], 'NET_NAME must be quoted')
        name = text(block[0][0])
        require(name not in nets, 'Duplicate net: ' + name)
        nodes = []
        for node in sections(block, 'NODE_NAME'):
            require(len(node) >= 3 and node[2][1], 'Truncated NODE_NAME')
            refdes, pin = node[0][0].upper(), node[1][0]
            require(refdes in components and pin in components[refdes]['pins'], 'Unknown node: ' + refdes + '.' + pin)
            require(instance_owners.get(node[2][0]) == refdes, 'Node instance path does not match component: ' + refdes + '.' + pin)
            key = (refdes, pin)
            require(key not in assigned or assigned[key] == name, 'Pin belongs to multiple nets: ' + refdes + '.' + pin)
            if key not in assigned:
                nodes.append({'refdes': refdes, 'pin': pin})
            assigned[key] = name
        require(nodes, 'Net without nodes: ' + name)
        first_node = next((i for i, token in enumerate(block) if is_word(token, 'NODE_NAME')), len(block))
        nets[name] = {'nodes': nodes, 'properties': properties(block[1:first_node])}
    companions = {p.name: digest(p) for p in directory.iterdir()
                  if p.is_file() and p.name.lower().startswith('pst') and p.name not in names
                  and p.suffix.lower() in ('.dat', '.dcf', '.cdsz')}
    return {'schema': 1, 'scope': 'connectivity_and_properties', 'encoding': encoding, 'sources': sources,
            'companions': companions, 'devices': devices, 'components': components, 'nets': nets,
            'notes': ['XY/SCH_LOC are schematic coordinates, not PCB placement.',
                      'External constraints are preserved by native import, not decoded by this reader.']}


def read_placement(path):
    units, version, rows = None, None, []
    for raw in Path(path).read_text(encoding='utf-8-sig').splitlines():
        line = raw.strip()
        if not line or line.startswith(('#', '(')):
            continue
        header = re.fullmatch(r'(VERSION|UUNITS)\s*=\s*(\S+)', line)
        if header and header[1] == 'VERSION':
            require(version is None, 'Duplicate placement VERSION')
            version = header[2]
            require(version == '2.0', 'Unsupported placement version')
            continue
        if header and header[1] == 'UUNITS':
            require(units is None, 'Duplicate placement units')
            units = UNIT_NAMES.get(header[2].upper())
            require(units is not None, 'Supported placement units: mm or mil')
            continue
        require(units is not None, 'Placement units must precede components')
        require(version == '2.0' and '!' in line, 'Expected VERSION 2.0 placement with ! columns')
        fields = [v.strip() for v in line.split('!')]
        require(len(fields) == 7, 'Placement requires seven columns')
        refdes, x, y, rotation, mirror, symbol, embedded = fields
        require(mirror in ('', 'm', 'M') and not embedded, 'Only top/bottom surface placement is supported')
        rows.append({'refdes': text(refdes).upper(), 'xy': [fmt(x), fmt(y)],
                     'rotation': fmt(angle(rotation)), 'side': 'bottom' if mirror else 'top',
                     'symbol': text(symbol)})
    require(units and version and rows, 'Empty or incomplete placement')
    require(len({r['refdes'] for r in rows}) == len(rows), 'Duplicate placement refdes')
    return {'schema': 1, 'units': units, 'components': rows}


def placement_text(plan):
    units = 'MILLIMETERS' if plan['units'] == 'mm' else 'MILS'
    lines = ['VERSION = 2.0', 'UUNITS = ' + units, '',
             '# refdes ! symbol_x ! symbol_y ! rotation ! mirror ! symbol_name ! embedded_layer']
    for row in plan['components']:
        require(all('!' not in text(row[k]) for k in ('refdes', 'symbol')), 'Placement field contains delimiter')
        lines.append(' ! '.join([row['refdes'].upper(), *map(fmt, row['xy']), fmt(row['rotation']),
                                 'm' if row['side'] == 'bottom' else '', row['symbol'], '']))
    return '\n'.join(lines) + '\n'


def verify_placement(plan, actual):
    require(plan['units'] in UNITS and actual['units'] in UNITS, 'Unknown placement units')
    expected = {p['refdes'].upper(): p for p in plan['components']}
    observed = {p['refdes'].upper(): p for p in actual['components']}
    require(len(expected) == len(plan['components']) and len(observed) == len(actual['components']), 'Duplicate placement refdes')
    require(set(expected) == set(observed), 'Placement component set mismatch')
    scale = UNITS[actual['units']] / UNITS[plan['units']]
    for refdes, p in expected.items():
        q = observed[refdes]
        require(p['symbol'].upper() == q['symbol'].upper() and p['side'] == q['side'], 'Placement symbol/side mismatch: ' + refdes)
        require(angle(p['rotation']) == angle(q['rotation']), 'Placement angle mismatch: ' + refdes)
        require(point(p['xy']) == [v * scale for v in point(q['xy'])], 'Placement coordinate mismatch: ' + refdes)
    return {'placement_verified': True, 'component_count': len(expected)}


def verify_connectivity(netlist, report):
    """Compare native Component Pin report to every logical physical pin."""
    validate_netlist(netlist)
    expected = {(refdes, pin): '' for refdes, component in netlist['components'].items()
                for pin in component['pins']}
    for name, net in netlist['nets'].items():
        for node in net['nodes']:
            expected[(node['refdes'], node['pin'])] = name
    required = {'REFDES', 'PIN_NUMBER', 'NET_NAME'}
    header, observed = None, {}
    with Path(report).open(encoding='utf-8-sig', newline='') as stream:
        for raw in csv.reader(stream, strict=True):
            fields = [value.strip() for value in raw]
            if not fields or not any(fields):
                continue
            if header is None:
                if required <= set(fields):
                    require(len(set(fields)) == len(fields), 'Duplicate native report column')
                    header = fields
                continue
            require(len(fields) == len(header), 'Malformed native Component Pin report row')
            row = dict(zip(header, fields))
            key = (text(row['REFDES']).upper(), text(row['PIN_NUMBER']))
            require(key not in observed, 'Duplicate native pin: ' + '.'.join(key))
            observed[key] = row['NET_NAME']
    require(header is not None, 'Missing Component Pin report header')
    require(set(observed) == set(expected), 'Native component/pin set differs from netlist')
    for key, name in expected.items():
        require(observed[key] == name, 'Native net mismatch on ' + '.'.join(key) + ': expected ' + repr(name) + ', observed ' + repr(observed[key]))
    return {'logical_connectivity_verified': True, 'physical_pin_count': len(expected),
            'net_count': len(netlist['nets'])}
