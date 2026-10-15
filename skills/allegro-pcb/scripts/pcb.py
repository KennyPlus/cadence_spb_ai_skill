#!/usr/bin/env python3
"""Data and native-operation tools for the AI-led allegro-pcb skill."""
import argparse
import csv
import json
from pathlib import Path
import sys

from formats import (digest, read_json, read_netlist, read_placement, require,
                     placement_text, verify_placement, write_json)
from model import placement_svg, resolve_routing, validate_placement
from native import REPORTS, Runtime, import_board, inventory, place_board, report_board, stage
from routing import router_do, verify_dsn


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest='command', required=True)
    netlist = commands.add_parser('netlist', help='Read the three PST files into a connectivity/property snapshot')
    netlist.add_argument('directory', type=Path)
    netlist.add_argument('--encoding', default='utf-8-sig')
    placement = commands.add_parser('placement', help='Check AI-authored placements and generate VERSION 2.0 text/SVG')
    placement.add_argument('plan', type=Path)
    placement.add_argument('--netlist', required=True, type=Path)
    placement.add_argument('--baseline', type=Path)
    reader = commands.add_parser('read-placement')
    reader.add_argument('file', type=Path)
    verify = commands.add_parser('verify-placement')
    verify.add_argument('plan', type=Path)
    verify.add_argument('file', type=Path)
    route = commands.add_parser('route', help='Generate selected-net Router commands from explicit model priorities')
    route.add_argument('plan', type=Path)
    route.add_argument('--netlist', required=True, type=Path)
    route.add_argument('--dsn', type=Path, help='Check selected nets and layer names against this native DSN')
    imp = commands.add_parser('native-import')
    imp.add_argument('directory', type=Path)
    imp.add_argument('--seed', type=Path)
    imp.add_argument('--library', action='append', type=Path, required=True)
    imp.add_argument('--encoding', default='utf-8-sig')
    place = commands.add_parser('native-place')
    place.add_argument('board', type=Path)
    place.add_argument('--plan', type=Path, required=True)
    place.add_argument('--netlist', type=Path, required=True)
    place.add_argument('--baseline', type=Path)
    place.add_argument('--library', action='append', type=Path, default=[], help='Compiled libraries needed for unplaced components; repeat as needed')
    report = commands.add_parser('native-report')
    report.add_argument('board', type=Path)
    report.add_argument('--report', choices=REPORTS, action='append', required=True)
    router = commands.add_parser('native-route')
    router.add_argument('dsn', type=Path)
    router.add_argument('--rules', type=Path, required=True, help='Reviewed companion *_rules.do from the same native export')
    router.add_argument('--plan', type=Path, required=True)
    router.add_argument('--netlist', type=Path, required=True)
    for command in commands.choices.values():
        command.add_argument('--out', type=Path, required=True, help='New job directory; existing paths are refused')
    for command in (imp, place, report, router):
        command.add_argument('--cadence-root', type=Path, required=True)
        command.add_argument('--env-file', type=Path, help='Source this existing Cadence Bash environment script before native execution (POSIX)')
        command.add_argument('--license', help='Existing legal license file or server setting; otherwise inherit environment')
        command.add_argument('--timeout', type=float, default=300)
    return root


def placement_job(args, out):
    plan, netlist = read_json(args.plan), read_json(args.netlist)
    baseline = read_json(args.baseline) if args.baseline else None
    result = validate_placement(plan, netlist, baseline)
    write_json(out / 'plan.json', plan)
    write_json(out / 'netlist.json', netlist)
    if baseline is not None:
        write_json(out / 'baseline.json', baseline)
    if not result['errors']:
        (out / 'place_txt.txt').write_text(placement_text(plan), encoding='utf-8')
        (out / 'placement.svg').write_text(placement_svg(plan), encoding='utf-8')
    return plan, result


def route_job(args, out):
    plan, netlist = read_json(args.plan), read_json(args.netlist)
    resolved = resolve_routing(plan, netlist)
    write_json(out / 'plan.json', plan)
    write_json(out / 'netlist.json', netlist)
    write_json(out / 'resolved.json', resolved)
    matched = verify_dsn(args.dsn, netlist, resolved) if args.dsn else {}
    (out / 'route.do').write_text(router_do(resolved), encoding='utf-8')
    return resolved, {'status': 'generated_only', 'native_verified': False, **matched,
                      'pending': ['native constraint persistence and effective-rule review',
                                  'Router execution, session import and native board readback']}


def execute(args):
    out = args.out.resolve()
    # Never recycle a job; stale native files must not look like new outputs.
    out.mkdir(parents=True, exist_ok=False)
    runtime = None
    result = {'status': 'failed', 'native_verified': False}
    try:
        if args.command == 'netlist':
            snapshot = read_netlist(args.directory, args.encoding)
            write_json(out / 'netlist.json', snapshot)
            result = {'status': 'parsed', 'native_verified': False,
                      'components': len(snapshot['components']), 'nets': len(snapshot['nets'])}
        elif args.command == 'read-placement':
            write_json(out / 'placement.json', read_placement(args.file))
            result = {'status': 'parsed', 'native_verified': False}
        elif args.command == 'verify-placement':
            result = {'status': 'placement_text_matched', 'native_verified': False,
                      **verify_placement(read_json(args.plan), read_placement(args.file))}
        elif args.command == 'placement':
            _, result = placement_job(args, out)
        elif args.command == 'route':
            _, result = route_job(args, out)
        else:
            require(args.timeout > 0 and args.timeout < float('inf'), 'Timeout must be finite and positive')
            runtime = Runtime(args, out)
            if args.command == 'native-import':
                result = import_board(runtime, args.directory, args.seed, args.library, args.encoding)
                write_json(out / 'netlist.json', result.pop('netlist'))
            elif args.command == 'native-place':
                plan, checked = placement_job(args, out)
                require(not checked['errors'], 'Placement model violates constraints')
                result = place_board(runtime, args.board, plan, read_json(out / 'netlist.json'), args.library)
            elif args.command == 'native-report':
                result = report_board(runtime, args.board, args.report)
            elif args.command == 'native-route':
                resolved, result = route_job(args, out)
                stage(args.dsn, out / 'source.dsn', runtime.sources)
                stage(args.rules, out / 'export_rules.do', runtime.sources)
                # Recheck staged bytes, so the executed file is the checked file.
                verify_dsn(out / 'source.dsn', read_json(out / 'netlist.json'), resolved)
                (out / 'route.do').write_text(router_do(resolved, True), encoding='utf-8')
                runtime.call('specctra', ['source.dsn', '-do', 'route.do', '-nog', '-quit'], 'routed.ses')
                result['status'] = 'native_route_candidate'
                result['pending'] = ['stage completion/conflict review', 'session import on unchanged export board',
                                     'effective BRD rules, physical connectivity, DRC and protected geometry readback']
            result.update(runtime.finish())
    except (OSError, ValueError, KeyError, TypeError, LookupError, csv.Error) as error:
        result = {'status': 'failed', 'native_verified': False, 'error': str(error)}
        if runtime:
            result.update(runs=runtime.runs, sources=runtime.sources)
            try:
                result.update(runtime.finish())
            except (OSError, ValueError) as changed:
                result['input_error'] = str(changed)
    result['files'] = inventory(out)
    write_json(out / 'result.json', result)
    return result


def main():
    args = parser().parse_args()
    try:
        result = execute(args)
    except (OSError, ValueError) as error:
        result = {'status': 'failed', 'error': str(error), 'native_verified': False}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 1 if result['status'] in ('failed', 'constraints_failed') else 0


if __name__ == '__main__':
    sys.exit(main())
