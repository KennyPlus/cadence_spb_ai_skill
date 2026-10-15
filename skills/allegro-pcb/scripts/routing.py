"""Compile explicit model decisions to selected-net PCB Router commands."""
from pathlib import Path
import re

from formats import digest, fmt, require


def sexpr(data):
    """Read data-only DSN/SKILL lists; do not evaluate Lisp or Router commands."""
    root, stack = [], []
    current = root
    i = 0
    while i < len(data):
        char = data[i]
        if char.isspace():
            i += 1
        elif char == ';':
            end = data.find('\n', i)
            i = len(data) if end < 0 else end + 1
        elif char == '(':
            child = []
            current.append(child); stack.append(current); current = child; i += 1
            require(len(stack) <= 100, 'Excessive S-expression nesting')
        elif char == ')':
            require(stack, 'Unexpected closing parenthesis')
            current = stack.pop(); i += 1
        elif char == '"':
            # DSN declares its quote character as (string_quote ").
            if current == ['string_quote'] and data[i + 1:].lstrip().startswith(')'):
                current.append('"'); i += 1; continue
            i += 1; value = []
            while i < len(data) and data[i] != '"':
                if data[i] == '\\':
                    i += 1
                    require(i < len(data) and data[i] in ('"', '\\'), 'Unsupported string escape')
                value.append(data[i]); i += 1
            require(i < len(data), 'Unterminated quoted string')
            current.append(''.join(value)); i += 1
        else:
            end = i
            while i < len(data) and not data[i].isspace() and data[i] not in '();"':
                i += 1
            require(i > end, 'Invalid token')
            current.append(data[end:i])
    require(not stack, 'Unclosed S-expression')
    return root


def children(node, kind):
    return [v for v in node if isinstance(v, list) and v and v[0] == kind]


def verify_dsn(path, netlist, resolved):
    root = sexpr(Path(path).read_text(encoding='utf-8-sig'))
    require(len(root) == 1 and root[0][:1] == ['pcb'], 'Expected one PCB DSN document')
    design = root[0]
    networks = children(design, 'network')
    require(len(networks) == 1, 'DSN needs one network section')
    nets = {}
    for node in children(networks[0], 'net'):
        require(len(node) >= 2 and isinstance(node[1], str) and node[1] not in nets, 'Invalid/duplicate DSN net')
        pins = children(node, 'pins')
        require(len(pins) == 1 and all(isinstance(p, str) for p in pins[0][1:]), 'Expected explicit DSN pins')
        require(len(set(pins[0][1:])) == len(pins[0][1:]), 'Duplicate DSN pin')
        nets[node[1]] = set(pins[0][1:])
    # Selected nets must match real exported connectivity, not merely a name.
    for group in resolved['groups']:
        for name in group['nets']:
            expected = {n['refdes'] + '-' + n['pin'] for n in netlist['nets'][name]['nodes']}
            require(len(expected) >= 2, 'Routing requires at least two physical pins: ' + name)
            require(name in nets and nets[name] == expected, 'DSN connectivity differs for selected net: ' + name)
    structures = children(design, 'structure')
    require(len(structures) == 1, 'DSN needs one structure section')
    layers = {v[1] for v in children(structures[0], 'layer') if len(v) >= 2}
    for group in resolved['groups']:
        require(set(group.get('layers', [])) <= layers, 'Requested layer missing from DSN')
    return {'dsn_sha256': digest(path), 'selected_connectivity_matched': True,
            'net_count': len(nets), 'layers': sorted(layers)}


def selector(name):
    # Quoting does not make wildcard selectors literal in PCB Router.
    require(isinstance(name, str) and re.fullmatch(r'[A-Za-z0-9_./:+-]+', name),
            'Unsupported Router selector: ' + str(name))
    return '"' + name + '"'


def router_do(resolved, include_export_rules=False):
    lines = ['# Generated from explicit AI decisions. Inspect native rules and results.']
    if include_export_rules:
        lines.append('do "export_rules.do"')
    lines += ['unit ' + resolved['units'], 'protect all wires', 'protect all vias',
              'set dynamic_pinswap off']
    for index, group in enumerate(resolved['groups'], 1):
        lines += ['', '# Stage ' + str(index) + ': ' + group['name'], 'unselect all nets']
        for name in group['nets']:
            net = selector(name)
            lines += [f'rule net {net} (width {fmt(group["width"])})',
                      f'rule net {net} (clearance {fmt(group["clearance"])})']
            if 'max_vias_per_connection' in group:
                lines.append(f'rule net {net} (limit_vias {group["max_vias_per_connection"]})')
            if 'layers' in group:
                lines.append(f'circuit net {net} (use_layer {" ".join(selector(v) for v in group["layers"])})')
            lines.append('select net ' + net)
        lines += ['route ' + str(resolved['passes']),
                  'write session "stage_' + str(index).zfill(2) + '.ses"']
        # Subsequent stages cannot rip up already routed critical wires/vias.
        lines += ['protect all wires', 'protect all vias']
    lines += ['write session "routed.ses"', '']
    return '\n'.join(lines)
