"""Check explicit AI-authored decisions; never infer placements or net priority."""
from html import escape
import math
import re

from formats import UNITS, angle, exact, number, point, require, text, validate_netlist


def orient(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def intersects(a, b, c, d):
    if max(a[0], b[0]) < min(c[0], d[0]) or max(c[0], d[0]) < min(a[0], b[0]):
        return False
    if max(a[1], b[1]) < min(c[1], d[1]) or max(c[1], d[1]) < min(a[1], b[1]):
        return False
    return orient(a, b, c) * orient(a, b, d) <= 0 and orient(c, d, a) * orient(c, d, b) <= 0


def polygon(value, accuracy):
    require(isinstance(value, list) and 4 <= len(value) <= 1000, 'Closed polygon needs 4..1000 points')
    pts = [tuple(map(float, point(p, accuracy))) for p in value]
    require(pts[0] == pts[-1], 'Polygon must explicitly repeat its first point')
    edges = list(zip(pts, pts[1:]))
    require(all(a != b for a, b in edges), 'Zero-length polygon edge')
    ring = pts[:-1]
    for i, b in enumerate(ring):
        a, c = ring[i - 1], ring[(i + 1) % len(ring)]
        require(orient(a, b, c) != 0 or (b[0]-a[0])*(c[0]-b[0]) + (b[1]-a[1])*(c[1]-b[1]) >= 0,
                'Polygon edge doubles back')
    for i, (a, b) in enumerate(edges):
        for j in range(i + 2, len(edges)):
            if (i, j) != (0, len(edges) - 1):
                require(not intersects(a, b, *edges[j]), 'Self-intersecting polygon')
    require(abs(sum(a[0]*b[1] - a[1]*b[0] for a, b in edges)) > 1e-12, 'Zero-area polygon')
    return pts


def point_segment(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = dx*dx + dy*dy
    t = max(0, min(1, ((p[0]-a[0])*dx + (p[1]-a[1])*dy) / length)) if length else 0
    return math.hypot(p[0]-a[0]-t*dx, p[1]-a[1]-t*dy)


def inside(p, poly):
    odd = False
    for a, b in zip(poly, poly[1:]):
        if point_segment(p, a, b) < 1e-10:
            return True
        if (a[1] > p[1]) != (b[1] > p[1]) and p[0] < (b[0]-a[0])*(p[1]-a[1])/(b[1]-a[1])+a[0]:
            odd = not odd
    return odd


def polygon_distance(a, b):
    if any(intersects(p, q, r, s) for p, q in zip(a, a[1:]) for r, s in zip(b, b[1:])):
        return 0.0
    return min(point_segment(p, r, s) for points, edges in ((a, b), (b, a))
               for p in points[:-1] for r, s in zip(edges, edges[1:]))


def transform(local, component):
    x, y = point(local)
    # Model convention: top-view symbol origins; mirror local X, then rotate.
    # Native pin readback must validate this convention for each library.
    if component['side'] == 'bottom':
        x = -x
    x, y = {0: (x, y), 90: (-y, x), 180: (-x, -y), 270: (y, -x)}[int(number(component['rotation']))]
    dx, dy = point(component['xy'])
    return float(x + dx), float(y + dy)


def footprint_polygon(footprint, component):
    x1, y1, x2, y2 = footprint['bounds']
    return [transform(p, component) for p in [[x1,y1],[x2,y1],[x2,y2],[x1,y2],[x1,y1]]]


def validate_placement(plan, netlist, baseline=None):
    validate_netlist(netlist)
    exact(plan, ['schema', 'units', 'accuracy', 'basis', 'board', 'footprints', 'components', 'rules'])
    require(type(plan['schema']) is int and plan['schema'] == 1 and plan['units'] in UNITS, 'Invalid placement schema/units')
    text(plan['basis']); accuracy = plan['accuracy']; number(0, accuracy)
    require(isinstance(netlist.get('components'), dict), 'Expected parsed netlist')
    board = plan['board']
    exact(board, ['outline', 'edge_clearance', 'component_clearance', 'keepouts'])
    outline = polygon(board['outline'], accuracy)
    edge_clearance = float(number(board['edge_clearance'], accuracy))
    gap = float(number(board['component_clearance'], accuracy))
    require(edge_clearance >= 0 and gap >= 0, 'Negative placement clearance')
    keepouts = []
    require(isinstance(board['keepouts'], list), 'Keepouts must be a list')
    for keepout in board['keepouts']:
        exact(keepout, ['name', 'polygon', 'sides', 'basis'])
        text(keepout['name']); text(keepout['basis'])
        require(isinstance(keepout['sides'], list) and keepout['sides'] and set(keepout['sides']) <= {'top', 'bottom'}, 'Invalid keepout sides')
        keepouts.append((keepout, polygon(keepout['polygon'], accuracy)))
    require(isinstance(plan['footprints'], dict) and plan['footprints'], 'Footprint geometry is required')
    for name, fp in plan['footprints'].items():
        text(name)
        exact(fp, ['bounds', 'pins', 'through', 'basis'])
        text(fp['basis'])
        require(type(fp['through']) is bool, 'through must be boolean')
        require(isinstance(fp['bounds'], list) and len(fp['bounds']) == 4, 'Footprint bounds require xmin,ymin,xmax,ymax')
        bounds = [number(v, accuracy) for v in fp['bounds']]
        require(bounds[0] < bounds[2] and bounds[1] < bounds[3], 'Invalid footprint bounds')
        require(isinstance(fp['pins'], dict) and fp['pins'], 'Explicit physical pin positions required')
        for pin, xy in fp['pins'].items():
            text(pin); x, y = point(xy, accuracy)
            require(bounds[0] <= x <= bounds[2] and bounds[1] <= y <= bounds[3], 'Physical pin is outside footprint bounds')
    require(isinstance(plan['components'], list) and plan['components'], 'Explicit component placements required')
    components, polygons = {}, {}
    for component in plan['components']:
        exact(component, ['refdes', 'symbol', 'xy', 'rotation', 'side', 'fixed', 'role', 'basis'])
        refdes = text(component['refdes']).upper(); text(component['role']); text(component['basis'])
        require(refdes not in components and refdes in netlist['components'], 'Unknown/duplicate refdes: ' + refdes)
        symbol = text(component['symbol'])
        require(symbol in plan['footprints'], 'Missing footprint geometry: ' + symbol)
        require(symbol.upper() == netlist['components'][refdes]['symbol'].upper(), 'Footprint differs from netlist: ' + refdes)
        require(set(netlist['components'][refdes]['pins']) <= set(plan['footprints'][symbol]['pins']), 'Footprint lacks physical pins: ' + refdes)
        point(component['xy'], accuracy)
        require(number(component['rotation']) in (0,90,180,270), 'Placement checker supports orthogonal rotations')
        require(component['side'] in ('top','bottom') and type(component['fixed']) is bool, 'Invalid side/fixed flag')
        components[refdes] = component
        polygons[refdes] = footprint_polygon(plan['footprints'][symbol], component)
    require(set(components) == set(netlist['components']), 'All logical components must have explicit placements')
    errors = []
    def issue(rule, refs, detail):
        errors.append({'rule': rule, 'components': refs, 'detail': detail})
    for refdes, poly in polygons.items():
        # Sample every edge between intersections as well as corners, so a
        # rectangle cannot bridge a concave board cutout undetected.
        on_board = all(inside(p, outline) for p in poly[:-1])
        for a, b in zip(poly, poly[1:]):
            cuts = [0.0, 1.0]
            dx, dy = b[0]-a[0], b[1]-a[1]
            for c, d in zip(outline, outline[1:]):
                ex, ey = d[0]-c[0], d[1]-c[1]
                den = dx*ey-dy*ex
                if abs(den) > 1e-12:
                    t = ((c[0]-a[0])*ey-(c[1]-a[1])*ex)/den
                    if 0 < t < 1 and intersects(a,b,c,d): cuts.append(t)
            cuts.sort()
            on_board = on_board and all(inside((a[0]+dx*(t+u)/2, a[1]+dy*(t+u)/2), outline) for t,u in zip(cuts,cuts[1:]))
        if not on_board or polygon_distance(poly, outline) + 1e-9 < edge_clearance:
            issue('board_edge', [refdes], 'Footprint exceeds outline or edge clearance')
        fp = plan['footprints'][components[refdes]['symbol']]
        sides = {'top', 'bottom'} if fp['through'] else {components[refdes]['side']}
        for keepout, shape in keepouts:
            if sides & set(keepout['sides']) and (polygon_distance(poly, shape) < 1e-9 or inside(poly[0], shape) or inside(shape[0], poly)):
                issue('keepout', [refdes], keepout['name'])
    for i, refdes in enumerate(components):
        a = components[refdes]; afp = plan['footprints'][a['symbol']]
        for other in list(components)[i+1:]:
            b = components[other]; bfp = plan['footprints'][b['symbol']]
            if a['side'] != b['side'] and not (afp['through'] or bfp['through']): continue
            pa, pb = polygons[refdes], polygons[other]
            distance = polygon_distance(pa, pb)
            if inside(pa[0], pb) or inside(pb[0], pa) or distance < 1e-9 or distance + 1e-9 < gap:
                issue('component_clearance', [refdes, other], 'Footprint bounds overlap or violate clearance')
    if baseline is not None:
        exact(baseline, ['units', 'components'], ['schema'])
        require('schema' not in baseline or type(baseline['schema']) is int and baseline['schema'] == 1,
                'Invalid baseline schema')
        require(baseline['units'] == plan['units'], 'Baseline units must match plan units')
        require(isinstance(baseline['components'], list), 'Baseline components must be a list')
        seen = set()
        for old in baseline['components']:
            exact(old, ['refdes', 'symbol', 'xy', 'rotation', 'side', 'fixed'])
            refdes = text(old['refdes']).upper()
            require(refdes not in seen, 'Duplicate baseline refdes: ' + refdes)
            seen.add(refdes)
            text(old['symbol']); point(old['xy']); angle(old['rotation'])
            require(old['side'] in ('top', 'bottom') and type(old['fixed']) is bool, 'Invalid baseline side/fixed')
            if old['fixed']:
                current = components.get(refdes)
                if current is None or not current['fixed'] or current['symbol'].upper() != old['symbol'].upper() or current['side'] != old['side'] or point(current['xy']) != point(old['xy']) or angle(current['rotation']) != angle(old['rotation']):
                    issue('fixed', [refdes], 'Fixed placement changed')
    def anchor(value):
        exact(value, ['refdes'], ['pin'])
        refdes = text(value['refdes']).upper(); require(refdes in components, 'Unknown rule refdes: ' + refdes)
        component = components[refdes]
        if 'pin' not in value: return tuple(map(float, point(component['xy'])))
        pins = plan['footprints'][component['symbol']]['pins']
        require(value['pin'] in pins, 'Unknown rule pin: ' + refdes + '.' + value['pin'])
        return transform(pins[value['pin']], component)
    require(isinstance(plan['rules'], list), 'Placement rules must be a list')
    for rule in plan['rules']:
        exact(rule, ['kind','from','to','min','max','basis'])
        text(rule['basis']); require(rule['kind'] in ('distance','delta_x','delta_y'), 'Unsupported placement rule kind')
        a, b = anchor(rule['from']), anchor(rule['to'])
        lower, upper = float(number(rule['min'], accuracy)), float(number(rule['max'], accuracy))
        require(lower <= upper and (rule['kind'] != 'distance' or lower >= 0), 'Invalid rule range')
        value = math.dist(a,b) if rule['kind'] == 'distance' else b[0 if rule['kind'] == 'delta_x' else 1] - a[0 if rule['kind'] == 'delta_x' else 1]
        if value < lower-1e-9 or value > upper+1e-9:
            issue(rule['kind'], [rule['from']['refdes'],rule['to']['refdes']], {'actual': value,'min':lower,'max':upper,'basis':rule['basis']})
    return {'status': 'checked_model' if not errors else 'constraints_failed', 'errors': errors,
            'native_verified': False, 'component_count': len(components),
            'scope': 'Explicit bounding boxes, board outline, keepouts, fixed and anchor rules; not native DRC or electrical approval.'}


def placement_svg(plan):
    outline = [[float(v) for v in point(p)] for p in plan['board']['outline']]
    xs, ys = [p[0] for p in outline], [p[1] for p in outline]
    margin = max(max(xs)-min(xs), max(ys)-min(ys)) * .08
    view = f'{min(xs)-margin} {-max(ys)-margin} {max(xs)-min(xs)+2*margin} {max(ys)-min(ys)+2*margin}'
    def points(poly): return ' '.join(f'{x},{-y}' for x,y in poly)
    output = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view}" width="1000" height="750">',
              '<rect width="100%" height="100%" fill="white"/>',
              f'<polygon points="{points(outline)}" fill="#f6f8fa" stroke="#333" stroke-width="{margin/30}"/>']
    for keepout in plan['board']['keepouts']:
        output.append(f'<polygon points="{points([[float(v) for v in point(p)] for p in keepout["polygon"]])}" fill="#f4b5b5" fill-opacity=".5"/>')
    for component in plan['components']:
        poly = footprint_polygon(plan['footprints'][component['symbol']], component)
        color = '#1768ac' if component['side'] == 'top' else '#b4436c'
        output.append(f'<polygon points="{points(poly)}" fill="{color}" fill-opacity=".25" stroke="{color}" stroke-width="{margin/35}"/>')
        x,y = map(float, point(component['xy']))
        output.append(f'<text x="{x}" y="{-y}" font-size="{margin/3}" text-anchor="middle">{escape(component["refdes"])}</text>')
    return '\n'.join(output + ['</svg>'])


def resolve_routing(plan, netlist):
    validate_netlist(netlist)
    exact(plan, ['schema','units','basis','groups','protected_nets','passes'])
    require(type(plan['schema']) is int and plan['schema'] == 1 and plan['units'] in UNITS, 'Invalid routing schema/units')
    text(plan['basis'])
    require(type(plan['passes']) is int and 1 <= plan['passes'] <= 100, 'Routing passes must be 1..100')
    require(isinstance(plan['groups'], list) and plan['groups'], 'AI must specify explicit routing groups')
    require(isinstance(plan['protected_nets'], list), 'protected_nets must be a list')
    require(set(plan['protected_nets']) <= set(netlist['nets']), 'Unknown protected net')
    assigned, groups, names = set(), [], set()
    for group in plan['groups']:
        exact(group, ['name','nets','priority','width','clearance','basis'], ['layers','max_vias_per_connection'])
        text(group['basis']); name = text(group['name'])
        require(re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,23}', name) and name.upper() not in names, 'Invalid/duplicate route group')
        names.add(name.upper())
        require(isinstance(group['nets'], list) and group['nets'] and len(set(group['nets'])) == len(group['nets']), 'Explicit nonempty unique net list required')
        require(set(group['nets']) <= set(netlist['nets']), 'Unknown net in route group: ' + name)
        require(not assigned.intersection(group['nets']) and not set(plan['protected_nets']).intersection(group['nets']), 'Overlapping route groups or protected net selected')
        require(type(group['priority']) is int and 1 <= group['priority'] <= 255, 'Priority must be 1..255; smaller runs first')
        require(number(group['width']) > 0 and number(group['clearance']) > 0, 'Positive width and copper clearance required')
        for net in group['nets']:
            require(re.fullmatch(r'[A-Za-z0-9_./:+-]+', net), 'Router selector metacharacters unsupported; use a reviewed native flow: ' + net)
        if 'layers' in group:
            require(isinstance(group['layers'], list) and group['layers'] and all(re.fullmatch(r'[A-Za-z0-9_./+-]+', v) for v in group['layers']), 'Invalid routing layers')
        if 'max_vias_per_connection' in group:
            require(type(group['max_vias_per_connection']) is int and 0 <= group['max_vias_per_connection'] <= 255, 'max_vias_per_connection must be 0..255')
        assigned.update(group['nets']); groups.append(dict(group))
    return {'schema':1, 'units':plan['units'], 'basis':plan['basis'],
            'groups':sorted(groups,key=lambda g:(g['priority'],g['name'])),
            'protected_nets':plan['protected_nets'], 'passes':plan['passes'],
            'unselected_nets':sorted(set(netlist['nets']) - assigned)}
