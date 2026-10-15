"""Synthetic behavioral checks for AI-authored PCB jobs; no Cadence required."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills' / 'allegro-pcb'
sys.path.insert(0, str(SKILL / 'scripts'))
import formats
import model
import native
import pcb
import routing


def fixture(name):
    return formats.read_json(SKILL / 'assets' / (name + '-example.json'))


def snapshot():
    return formats.read_netlist(SKILL / 'assets' / 'example-netlist')


def baseline(plan):
    keys = ('refdes', 'symbol', 'xy', 'rotation', 'side', 'fixed')
    return {'units': plan['units'], 'components': [{k: copy.deepcopy(c[k]) for k in keys} for c in plan['components']]}


DSN = '''(pcb "synthetic"
  (parser (string_quote "))
  (unit mm)
  (structure (layer TOP (type signal)) (layer BOTTOM (type signal)))
  (network
    (net DEMO_CLK (pins R1-1 R2-1))
    (net DEMO_GND (pins R1-2 R2-2))))
'''

CPN = '''Component Pin Report
synthetic.brd

REFDES,PIN_NUMBER,COMP_DEVICE_TYPE,PIN_TYPE,PIN_NAME,NET_NAME
R1,1,DEMO_RES,UNSPEC,A,DEMO_CLK
R1,2,DEMO_RES,UNSPEC,B,DEMO_GND
R2,1,DEMO_RES,UNSPEC,A,DEMO_CLK
R2,2,DEMO_RES,UNSPEC,B,DEMO_GND
'''


class NetlistTests(unittest.TestCase):
    def test_physical_pin_mapping_and_schematic_metadata(self):
        data = snapshot()
        self.assertEqual(data['components']['R1']['pins'], ['1', '2'])
        self.assertEqual(data['devices']['DEMO_RES']['pins']['A']['numbers'], ['1'])
        self.assertEqual(data['components']['R1']['properties']['XY'], '(500,200)')
        self.assertEqual(data['nets']['DEMO_CLK']['nodes'], [{'refdes':'R1','pin':'1'}, {'refdes':'R2','pin':'1'}])
        self.assertNotIn('xy', data['components']['R1'])
        self.assertEqual(len(data['sources']), 3)

    def mutate(self, filename, before, after):
        with tempfile.TemporaryDirectory() as folder:
            shutil.copytree(SKILL / 'assets' / 'example-netlist', Path(folder) / 'input')
            path = Path(folder) / 'input' / filename
            path.write_text(path.read_text(encoding='utf-8').replace(before, after), encoding='utf-8')
            return formats.read_netlist(path.parent)

    def test_unknown_node_and_multi_net_pin_are_rejected(self):
        for before, after in [('NODE_NAME R2 2', 'NODE_NAME R2 99'),
                              ('NODE_NAME R2 2', 'NODE_NAME R2 1'),
                              ('NODE_NAME R2 2', 'NODE_NAME R9 2')]:
            with self.subTest(after=after), self.assertRaises(ValueError):
                self.mutate('pstxnet.dat', before, after)

    def test_truncated_files_fail_instead_of_losing_connectivity(self):
        for filename in ('pstchip.dat', 'pstxprt.dat', 'pstxnet.dat'):
            with self.subTest(filename=filename), self.assertRaisesRegex(ValueError, 'END'):
                self.mutate(filename, 'END.', '')
        for end in ('end_pin;', 'end_body;', 'end_primitive;'):
            with self.subTest(end=end), self.assertRaises(ValueError):
                self.mutate('pstchip.dat', end, '')

    def test_unterminated_quoted_property_fails(self):
        with self.assertRaises(ValueError):
            formats.tokens("PIN_NUMBER='(1)")

    def test_companion_constraints_are_inventoried(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'input'
            shutil.copytree(SKILL / 'assets' / 'example-netlist', source)
            companion = source / 'pstcmdb.dat'
            companion.write_bytes(b'synthetic opaque constraint data')
            self.assertEqual(formats.read_netlist(source)['companions'], {companion.name: formats.digest(companion)})

    def test_duplicate_components_and_wrong_file_type_fail(self):
        for file, before, after in [('pstxprt.dat', "PART_NAME R2", "PART_NAME R1"),
                                   ('pstxnet.dat', 'EXPANDEDNETLIST', 'OTHER')]:
            with self.subTest(file=file), self.assertRaises(ValueError):
                self.mutate(file, before, after)

    def test_old_encoding_is_explicit(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'input'
            shutil.copytree(SKILL / 'assets' / 'example-netlist', source)
            part = source / 'pstxprt.dat'
            part.write_bytes(part.read_text(encoding='utf-8').replace("C_PATH='@DEMO'", "C_PATH='演示'").encode('gb18030'))
            with self.assertRaises(UnicodeError):
                formats.read_netlist(source)
            self.assertEqual(formats.read_netlist(source, 'gb18030')['components']['R1']['properties']['C_PATH'], '演示')

    def test_shared_instance_paths_and_misbound_nodes_fail(self):
        with self.assertRaisesRegex(ValueError, 'multiple components'):
            self.mutate('pstxprt.dat', '@DEMO:R2', '@DEMO:R1')
        with self.assertRaisesRegex(ValueError, 'instance path'):
            self.mutate('pstxnet.dat', '@DEMO:R1', '@DEMO:R2')

    def test_native_pin_report_detects_dropped_and_wrong_connections(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'cpn.txt'
            path.write_text(CPN, encoding='utf-8')
            matched = formats.verify_connectivity(snapshot(), path)
            self.assertTrue(matched['logical_connectivity_verified'])
            self.assertEqual(matched['physical_pin_count'], 4)
            for bad in (CPN.replace('R1,1,DEMO_RES,UNSPEC,A,DEMO_CLK', 'R1,1,DEMO_RES,UNSPEC,A,'),
                        CPN.replace('R1,1,DEMO_RES,UNSPEC,A,DEMO_CLK', 'R1,1,DEMO_RES,UNSPEC,A,DEMO_GND'),
                        CPN.replace('R1,1,DEMO_RES,UNSPEC,A,DEMO_CLK\n', ''),
                        CPN + 'R1,1,DEMO_RES,UNSPEC,A,DEMO_CLK\n'):
                path.write_text(bad, encoding='utf-8')
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    formats.verify_connectivity(snapshot(), path)


class PlacementTests(unittest.TestCase):
    def setUp(self):
        self.plan, self.netlist = fixture('placement'), snapshot()

    def check(self):
        return model.validate_placement(self.plan, self.netlist)

    def test_example_checks_explicit_geometry_without_native_claim(self):
        result = self.check()
        self.assertEqual(result['status'], 'checked_model')
        self.assertFalse(result['native_verified'])

    def test_overlap_side_and_through_hole_occupancy(self):
        self.plan['rules'] = []
        self.plan['components'][1]['xy'] = [8,10]
        self.assertFalse(self.check()['errors'])
        self.plan['components'][1]['side'] = 'top'
        self.assertIn('component_clearance', [e['rule'] for e in self.check()['errors']])
        self.plan['components'][1]['side'] = 'bottom'
        self.plan['footprints']['DEMO_R']['through'] = True
        self.assertIn('component_clearance', [e['rule'] for e in self.check()['errors']])

    def test_board_edge_keepout_and_tight_spacing_are_detected(self):
        self.plan['rules'] = []
        for xy, expected in [([0,10], 'board_edge'), ([26,10], 'keepout'), ([10.6,10], 'component_clearance')]:
            self.plan['components'][1].update(xy=xy, side='top')
            with self.subTest(xy=xy):
                self.assertIn(expected, [e['rule'] for e in self.check()['errors']])

    def test_concave_cutout_between_corners_is_detected(self):
        self.plan['board'] = {'outline':[[0,0],[10,0],[10,10],[6,10],[6,4],[4,4],[4,10],[0,10],[0,0]],
                              'edge_clearance':0, 'component_clearance':0, 'keepouts':[]}
        self.plan['rules'] = []
        self.plan['footprints']['DEMO_R']['bounds'] = [-2,-1,2,1]
        self.plan['components'][0]['xy'] = [5,4]
        self.plan['components'][1]['xy'] = [2,2]
        errors = self.check()['errors']
        self.assertTrue(any(e['rule'] == 'board_edge' and e['components'] == ['R1'] for e in errors))

    def test_mirrored_pin_anchor_uses_declared_model_convention(self):
        component = {'xy':[10,20], 'rotation':90, 'side':'bottom'}
        self.assertEqual(model.transform([1,0.5], component), (9.5,19.0))
        self.plan['rules'][0]['max'] = 7
        self.assertIn('distance', [e['rule'] for e in self.check()['errors']])

    def test_fixed_baseline_rejects_changes_and_misspelled_flags(self):
        old = baseline(self.plan)
        self.plan['components'][0]['xy'][0] += 0.5
        result = model.validate_placement(self.plan, self.netlist, old)
        self.assertIn('fixed', [e['rule'] for e in result['errors']])
        old['components'][0]['fixd'] = old['components'][0].pop('fixed')
        with self.assertRaises(ValueError):
            model.validate_placement(self.plan, self.netlist, old)

    def test_invalid_baseline_types_and_duplicates_fail(self):
        for fixed in ('false', 0, None):
            old = baseline(self.plan); old['components'][0]['fixed'] = fixed
            with self.subTest(fixed=fixed), self.assertRaises(ValueError):
                model.validate_placement(self.plan, self.netlist, old)
        old = baseline(self.plan); old['components'].append(old['components'][0])
        with self.assertRaises(ValueError):
            model.validate_placement(self.plan, self.netlist, old)

    def test_precision_nonfinite_or_incomplete_geometry_fail(self):
        for value in ('NaN', 'Infinity', True, '8.00001'):
            self.plan['components'][0]['xy'][0] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.check()
        self.plan = fixture('placement')
        del self.plan['footprints']['DEMO_R']['pins']['2']
        with self.assertRaises(ValueError):
            self.check()

    def test_inconsistent_bounds_and_backtracking_polygon_fail(self):
        self.plan['footprints']['DEMO_R']['bounds'] = [-0.1,-0.1,0.1,0.1]
        with self.assertRaises(ValueError):
            self.check()
        with self.assertRaises(ValueError):
            model.polygon([[0,0],[10,0],[5,0],[10,10],[0,10],[0,0]], 3)

    def test_duplicate_json_fields_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'model.json'
            path.write_text('{"fixed":true,"fixed":false}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Duplicate JSON'):
                formats.read_json(path)

    def test_placement_roundtrip_mil_conversion_and_negative_angle(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'placement.txt'
            path.write_text(formats.placement_text(self.plan), encoding='utf-8')
            self.assertTrue(formats.verify_placement(self.plan, formats.read_placement(path))['placement_verified'])
            path.write_text('VERSION = 2.0\nUUNITS = MILS\nR1 ! -1000 ! 0 ! -90 ! m ! DEMO_R !\n', encoding='utf-8')
            expected = {'units':'mm', 'components':[{'refdes':'R1','symbol':'DEMO_R','xy':['-25.4',0], 'rotation':270, 'side':'bottom'}]}
            self.assertTrue(formats.verify_placement(expected, formats.read_placement(path))['placement_verified'])

    def test_embedded_layer_duplicate_refdes_and_nonfinite_text_fail(self):
        for row in ('R1 ! 0 ! 0 ! 0 ! ! DEMO_R ! INNER',
                    'R1 ! NaN ! 0 ! 0 ! ! DEMO_R !',
                    'R1 ! 0 ! 0 ! 0 ! ! DEMO_R !\nR1 ! 1 ! 0 ! 0 ! ! DEMO_R !'):
            with self.subTest(row=row), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'p.txt'
                path.write_text('VERSION = 2.0\nUUNITS = MILLIMETERS\n' + row, encoding='utf-8')
                with self.assertRaises(ValueError):
                    formats.read_placement(path)


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.plan, self.netlist = fixture('routing'), snapshot()

    def test_interaction_updates_width_and_order_without_inference(self):
        self.plan['groups'][1]['priority'] = 1
        self.plan['groups'][0].update(priority=200, width=0.25)
        resolved = model.resolve_routing(self.plan, self.netlist)
        text = routing.router_do(resolved)
        self.assertLess(text.index('select net "DEMO_GND"'), text.index('select net "DEMO_CLK"'))
        self.assertIn('rule net "DEMO_CLK" (width 0.25)', text)
        self.assertIn('rule net "DEMO_CLK" (limit_vias 2)', text)
        self.assertEqual(text.count('unselect all nets'), 2)
        self.assertEqual(text.count('protect all vias'), 3)
        self.assertNotIn('unprotect', text)
        self.assertNotIn('priority', self.netlist['nets']['DEMO_CLK'])

    def test_omitted_nets_are_not_implicitly_routed(self):
        self.plan['groups'] = self.plan['groups'][:1]
        self.plan['protected_nets'] = ['DEMO_GND']
        resolved = model.resolve_routing(self.plan, self.netlist)
        self.assertEqual(resolved['unselected_nets'], ['DEMO_GND'])
        self.assertNotIn('select net "DEMO_GND"', routing.router_do(resolved))

    def test_empty_unknown_protected_or_overlapping_selections_fail(self):
        for nets in ([], ['UNKNOWN'], ['DEMO_GND'], ['DEMO_CLK', 'DEMO_CLK']):
            self.plan['groups'][0]['nets'] = nets
            with self.subTest(nets=nets), self.assertRaises(ValueError):
                model.resolve_routing(self.plan, self.netlist)
        self.plan = fixture('routing'); self.plan['protected_nets'] = ['DEMO_CLK']
        with self.assertRaises(ValueError):
            model.resolve_routing(self.plan, self.netlist)

    def test_selector_wildcards_and_unknown_constraints_fail(self):
        for name in ('CLK*', 'BUS[0]', 'CLK?','CLK\nroute 100', 'CLK"'):
            self.netlist = snapshot()
            self.netlist['nets'][name] = self.netlist['nets'].pop('DEMO_CLK')
            self.plan['groups'][0]['nets'] = [name]
            with self.subTest(name=name), self.assertRaises(ValueError):
                model.resolve_routing(self.plan, self.netlist)
        self.netlist = snapshot()
        self.plan = fixture('routing'); self.plan['groups'][0]['impedance'] = 50
        with self.assertRaises(ValueError):
            model.resolve_routing(self.plan, self.netlist)

    def test_native_via_limit_range_is_enforced(self):
        for value in (-1, 256, True, 2.5):
            self.plan['groups'][0]['max_vias_per_connection'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                model.resolve_routing(self.plan, self.netlist)

    def test_malformed_snapshot_fails_with_validation_error(self):
        for value in ([], None, {}, {'schema':1, 'components':{}, 'nets':{}}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                model.resolve_routing(self.plan, value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                model.validate_placement(fixture('placement'), value)

    def test_dsn_requires_real_pins_layers_and_nonempty_routable_net(self):
        resolved = model.resolve_routing(self.plan, self.netlist)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'board.dsn'
            path.write_text(DSN, encoding='utf-8')
            self.assertTrue(routing.verify_dsn(path, self.netlist, resolved)['selected_connectivity_matched'])
            for bad in (DSN.replace('R2-1', 'R2-2'), DSN.replace('DEMO_CLK', 'OLD_CLK'), DSN.replace('BOTTOM', 'INNER')):
                path.write_text(bad, encoding='utf-8')
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    routing.verify_dsn(path, self.netlist, resolved)
            path.write_text(DSN.replace(' R2-1', ''), encoding='utf-8')
            self.netlist['nets']['DEMO_CLK']['nodes'].pop()
            with self.assertRaises(ValueError):
                routing.verify_dsn(path, self.netlist, resolved)


class NativeBoundaryTests(unittest.TestCase):
    def args(self, folder, command):
        root = Path(folder)
        cadence = root / 'cadence'; cadence.mkdir()
        board = root / 'original.brd'; board.write_bytes(b'synthetic native board identity')
        plan = root / 'plan.json'; formats.write_json(plan, fixture('placement'))
        netlist = root / 'netlist.json'; formats.write_json(netlist, snapshot())
        return SimpleNamespace(command=command, out=root/'job', cadence_root=cadence, license=None,
                               timeout=2, board=board, plan=plan, netlist=netlist, baseline=None, library=[])

    def test_native_placement_readback_is_narrow_and_source_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            args = self.args(folder, 'native-place'); before = formats.digest(args.board)
            calls = []
            def fake(runtime, program, arguments, output=None):
                calls.append((program, arguments))
                if program == 'report':
                    (runtime.job / output).write_text(CPN, encoding='utf-8')
                elif output.endswith('.brd'):
                    (runtime.job / output).write_bytes(b'candidate')
                else:
                    shutil.copyfile(runtime.job / 'place_txt.txt', runtime.job / output)
            with patch.object(native.Runtime, 'call', fake):
                result = pcb.execute(args)
            self.assertEqual(result['status'], 'native_placement_matched')
            self.assertTrue(result['logical_connectivity_verified'])
            self.assertFalse(result['native_verified'])
            self.assertTrue(result['sources_unchanged'])
            self.assertEqual(before, formats.digest(args.board))
            self.assertEqual(calls[0][1][:2], ['-r','-m'])
            self.assertNotIn('-z', calls[0][1])
            self.assertIn('FIXED properties requested by the model', result['pending'])

    def test_placement_candidate_with_lost_connectivity_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            args = self.args(folder, 'native-place')
            def fake(runtime, program, arguments, output=None):
                if program == 'report':
                    (runtime.job/output).write_text(CPN.replace('R1,1,DEMO_RES,UNSPEC,A,DEMO_CLK', 'R1,1,DEMO_RES,UNSPEC,A,'), encoding='utf-8')
                elif output.endswith('.brd'):
                    (runtime.job/output).write_bytes(b'candidate')
                else:
                    shutil.copyfile(runtime.job/'place_txt.txt', runtime.job/output)
            with patch.object(native.Runtime, 'call', fake):
                result = pcb.execute(args)
            self.assertEqual(result['status'], 'failed')
            self.assertIn('Native net mismatch on R1.1', result['error'])

    def test_zero_exit_timeout_fails_even_if_output_exists(self):
        with tempfile.TemporaryDirectory() as folder:
            args = self.args(folder, 'native-place')
            binary = args.cadence_root / ('tools/bin/plctxt.exe' if os.name == 'nt' else 'tools.lnx86/bin/plctxt')
            binary.parent.mkdir(parents=True); binary.write_bytes(b'fake native executable')
            def fake_run(command, cwd, env, timeout, log):
                (cwd / 'placed.brd').write_bytes(b'partial output')
                return {'returncode':0, 'timed_out':True}
            with patch.object(native, 'run_process', fake_run), patch.object(native.shutil, 'which', return_value='xvfb-run'):
                result = pcb.execute(args)
            self.assertEqual(result['status'], 'failed')
            self.assertFalse(result['native_verified'])
            self.assertFalse((args.out / 'actual.txt').exists())

    def test_zero_exit_with_logged_error_is_a_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            args = self.args(folder, 'native-place')
            binary = args.cadence_root / ('tools/bin/plctxt.exe' if os.name == 'nt' else 'tools.lnx86/bin/plctxt')
            binary.parent.mkdir(parents=True); binary.write_bytes(b'fake native executable')
            def fake_run(command, cwd, env, timeout, log):
                (cwd / 'placed.brd').write_bytes(b'partial output')
                Path(log).write_text('Error: Symbol or pad not found\nSuccessfully placed 0 components\n', encoding='utf-8')
                return {'returncode':0, 'timed_out':False}
            with patch.object(native, 'run_process', fake_run), patch.object(native.shutil, 'which', return_value='xvfb-run'):
                result = pcb.execute(args)
            self.assertEqual(result['status'], 'failed')
            self.assertIn('Native log reports an error', result['error'])

    def test_placement_stages_compiled_libraries_for_unplaced_parts(self):
        with tempfile.TemporaryDirectory() as folder:
            args = self.args(folder, 'native-place')
            library = Path(folder) / 'input-library'; library.mkdir()
            (library/'DEMO_R.psm').write_bytes(b'synthetic footprint')
            (library/'DEMO_PAD.pad').write_bytes(b'synthetic pad')
            args.library = [library]
            def fake(runtime, program, arguments, output=None):
                self.assertTrue((runtime.job/'library/demo_r.psm').is_file())
                self.assertTrue((runtime.job/'library/demo_pad.pad').is_file())
                self.assertIn('set psmpath = ./library', (runtime.job/'pcbenv/env').read_text(encoding='utf-8'))
                if program == 'report':
                    (runtime.job/output).write_text(CPN, encoding='utf-8')
                elif output.endswith('.brd'):
                    (runtime.job/output).write_bytes(b'candidate')
                else:
                    shutil.copyfile(runtime.job/'place_txt.txt', runtime.job/output)
            with patch.object(native.Runtime, 'call', fake):
                result = pcb.execute(args)
            self.assertEqual(result['status'], 'native_placement_matched')
            self.assertEqual(len(result['sources']), 3)

    @unittest.skipIf(os.name == 'nt', 'POSIX process group lifecycle')
    def test_timeout_kills_and_reaps_native_process(self):
        with tempfile.TemporaryDirectory() as folder:
            result = native.run_process([sys.executable, '-c', 'import time;time.sleep(30)'],
                                        folder, dict(os.environ), .1, Path(folder)/'log')
            self.assertTrue(result['timed_out'])
            self.assertNotEqual(result['returncode'], 0)

    def test_missing_native_program_never_reports_success(self):
        with tempfile.TemporaryDirectory() as folder:
            args = self.args(folder, 'native-place')
            result = pcb.execute(args)
            self.assertEqual(result['status'], 'failed')
            self.assertIn('Native program missing', result['error'])
            self.assertTrue((args.out / 'result.json').is_file())

    def test_native_router_rejects_stale_netlist_before_process_start(self):
        with tempfile.TemporaryDirectory() as folder:
            args = self.args(folder, 'native-route')
            formats.write_json(args.plan, fixture('routing'))
            args.dsn = Path(folder)/'bad.dsn'; args.dsn.write_text(DSN.replace('R2-1', 'R2-2'), encoding='utf-8')
            args.rules = Path(folder)/'rules.do'; args.rules.write_text('# synthetic', encoding='utf-8')
            with patch.object(native, 'run_process') as runner:
                result = pcb.execute(args)
            runner.assert_not_called()
            self.assertEqual(result['status'], 'failed')

    def test_conflicting_compiled_libraries_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); paths = []
            for index in range(2):
                directory = root / str(index); directory.mkdir()
                (directory/'demo.psm').write_bytes(bytes([index]))
                paths.append(directory)
            runtime = SimpleNamespace(job=root/'job', sources={})
            with self.assertRaisesRegex(ValueError, 'Conflicting'):
                native.stage_libraries(runtime, paths)


@unittest.skipIf(os.name == 'nt', 'Cadence Bash environment sourcing is POSIX-only')
class EnvironmentTests(unittest.TestCase):
    def test_source_preserves_export_unset_and_literal_values(self):
        with tempfile.TemporaryDirectory(prefix='pcb env ') as folder:
            path = Path(folder) / 'setup $(touch UNEXPECTED).sh'
            path.write_text("echo startup banner\nexport PCB_TEST_VALUE='a=b\nsecond line'\n"
                            "export CDS_LIC_FILE='/example/license.dat'\n"
                            "export LD_LIBRARY_PATH='/example/cadence/lib'\n"
                            'unset PCB_TEST_REMOVE\n', encoding='utf-8')
            with patch.dict(os.environ, {'PCB_TEST_REMOVE':'parent', 'PCB_TEST_VALUE':'original'}):
                loaded, sources = native.load_environment(path)
                self.assertEqual(loaded['PCB_TEST_VALUE'], 'a=b\nsecond line')
                self.assertEqual(loaded['CDS_LIC_FILE'], '/example/license.dat')
                self.assertEqual(loaded['LD_LIBRARY_PATH'], '/example/cadence/lib')
                self.assertNotIn('PCB_TEST_REMOVE', loaded)
                self.assertEqual(os.environ['PCB_TEST_REMOVE'], 'parent')
                self.assertEqual(os.environ['PCB_TEST_VALUE'], 'original')
            self.assertEqual(sources, {str(path): formats.digest(path)})
            self.assertFalse((Path(folder)/'UNEXPECTED').exists())

    def test_failed_or_early_exit_environment_never_falls_back(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'env.sh'
            for body in ('export PCB_TEST_VALUE=partial\nreturn 17\n', 'exit 0\n'):
                path.write_text(body, encoding='utf-8')
                with self.subTest(body=body), self.assertRaises(ValueError):
                    native.load_environment(path)

    def test_environment_timeout_is_reaped(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'env.sh'; path.write_text('sleep 30\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'timed out'):
                native.load_environment(path, timeout=.1)

    def test_runtime_uses_sourced_environment_and_explicit_license_override(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            setup = root/'env.sh'
            setup.write_text("export CDS_LIC_FILE='/example/default.lic'\n"
                             "export LD_LIBRARY_PATH='/example/runtime/lib'\n", encoding='utf-8')
            args = SimpleNamespace(cadence_root=root, env_file=setup, license='/example/override.lic', timeout=3)
            job = root/'job'; job.mkdir()
            runtime = native.Runtime(args, job)
            self.assertEqual(runtime.env['LD_LIBRARY_PATH'], '/example/runtime/lib')
            self.assertEqual(runtime.env['CDS_LIC_FILE'], '/example/override.lic')
            self.assertEqual(runtime.env['ALLEGRO_PCBENV'], str(job/'pcbenv'))
            result = runtime.finish()
            self.assertEqual(result['environment']['mode'], 'sourced')
            self.assertTrue(result['environment']['license_configured'])
            self.assertNotIn('/example/override.lic', json.dumps(result))
            self.assertNotIn('/example/runtime/lib', json.dumps(result))
            self.assertFalse((job/'env.sh').exists())


class InstalledSkillTests(unittest.TestCase):
    def test_manifest_only_copy_works_outside_repo_and_rejects_stale_jobs(self):
        manifest = formats.read_json(ROOT/'scripts'/'skill-files.json')['allegro-pcb']
        with tempfile.TemporaryDirectory(prefix='installed pcb ') as folder:
            root = Path(folder); installed = root/'skill'
            for relative in manifest:
                path = installed/relative; path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(SKILL/relative, path)
            def cli(*arguments):
                return subprocess.run([sys.executable, str(installed/'scripts'/'pcb.py'), *map(str, arguments)],
                                      cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=15)
            netlist, placement, route = root/'netlist', root/'placement', root/'route'
            one = cli('netlist', installed/'assets/example-netlist', '--out', netlist)
            self.assertEqual(one.returncode, 0, one.stdout+one.stderr)
            two = cli('placement', installed/'assets/placement-example.json', '--netlist', netlist/'netlist.json', '--out', placement)
            self.assertEqual(two.returncode, 0, two.stdout+two.stderr)
            self.assertTrue((placement/'placement.svg').is_file())
            three = cli('route', installed/'assets/routing-example.json', '--netlist', netlist/'netlist.json', '--out', route)
            self.assertEqual(three.returncode, 0, three.stdout+three.stderr)
            before = formats.digest(placement/'result.json')
            retry = cli('placement', installed/'assets/placement-example.json', '--netlist', netlist/'netlist.json', '--out', placement)
            self.assertEqual(retry.returncode, 1)
            self.assertEqual(before, formats.digest(placement/'result.json'))
            bad = fixture('placement'); bad['components'][1]['xy'] = [100,100]
            formats.write_json(root/'bad.json', bad)
            fail = cli('placement', root/'bad.json', '--netlist', netlist/'netlist.json', '--out', root/'bad-output')
            self.assertEqual(fail.returncode, 1)
            self.assertEqual(json.loads(fail.stdout)['status'], 'constraints_failed')
            self.assertFalse((root/'bad-output'/'place_txt.txt').exists())


if __name__ == '__main__':
    unittest.main()
