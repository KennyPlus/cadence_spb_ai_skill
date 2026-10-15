import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills/orcad-schematic'
ASSETS = SKILL / 'assets'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


sch = module('schematic_under_test', SKILL / 'scripts/schematic.py')
pst = module('schematic_pst_reader', ROOT / 'skills/allegro-pcb/scripts/formats.py')


class SchematicTests(unittest.TestCase):
    def setUp(self):
        self.plan = sch.read_json(ASSETS / 'design-example.json')
        self.library = sch.read_xml(ASSETS / 'library-example.xml')
        self.profile = sch.read_json(ASSETS / 'profile-example.json')
        self.template = sch.read_xml(ASSETS / 'template-example.xml')

    def check(self):
        return sch.check(self.plan, self.library, self.profile)

    def command(self, command, out, extra=(), plan=None, script=None):
        args = [sys.executable, str(script or SKILL / 'scripts/schematic.py'), command,
                str(plan or ASSETS / 'design-example.json'), '--library', str(ASSETS / 'library-example.xml'),
                '--profile', str(ASSETS / 'profile-example.json'), '--out', str(out), *map(str, extra)]
        return subprocess.run(args, capture_output=True, text=True)

    def test_model_xml_and_pst_roundtrip(self):
        result, catalog = self.check()
        self.assertEqual(result['diagnostics'], [])
        self.assertEqual(result['physical_pin_count'], 6)
        before = ET.tostring(self.template)
        xml = sch.design_xml(self.plan, self.library, catalog, self.template)
        self.assertEqual(ET.tostring(self.template), before)
        inventory = sch.inspect_xml(xml)
        self.assertEqual(len(inventory['pages'][0]['parts']), 3)
        self.assertEqual(len(xml.findall('.//PartInst')), 3)
        with tempfile.TemporaryDirectory() as temp:
            for name, data in sch.pst(self.plan, catalog).items():
                (Path(temp) / name).write_text(data, encoding='utf-8')
            actual = pst.read_netlist(temp)
        self.assertEqual(sch.verify_netlist(sch.expected_netlist(self.plan, catalog), actual)['status'], 'netlist_matches_model')
        self.assertFalse(result['native_capture_verified'])

    def test_instances_resolve_the_embedded_cache_and_single_device(self):
        self.library.find('.//LibPart/Defn').set('CellName', 'SEPARATE_GRAPHIC')
        _, catalog = self.check()
        xml = sch.design_xml(self.plan, self.library, catalog, self.template)
        cached = xml.find('Cache/Package/Defn')
        names = set()
        for inst in xml.findall('.//PartInst'):
            attrs = inst.find('Defn').attrib
            self.assertEqual(attrs['libName'], cached.get('sourceLibName'))
            self.assertEqual(attrs['pkgName'], cached.get('name'))
            self.assertEqual(attrs['deviceDesignator'], '')
            self.assertEqual(inst.find('GraphicName/Defn').get('name'), 'SEPARATE_GRAPHIC.Normal')
            names.add(attrs['name'])
        self.assertEqual(len(names), len(self.plan['parts']))

    def xml_model(self):
        _, catalog = self.check()
        return sch.design_xml(self.plan, self.library, catalog, self.template)

    def test_headless_xml_reconstructs_the_physical_graph(self):
        result, plan, catalog = sch.checked_xml(self.xml_model(), self.profile, 10)
        self.assertEqual(result['status'], 'checked_xml')
        _, original = self.check()
        self.assertEqual(sch.verify_netlist(sch.expected_netlist(self.plan, original), sch.expected_netlist(plan, catalog))['status'], 'netlist_matches_model')
        self.assertEqual([p['at'] for p in plan['parts']], [p['at'] for p in self.plan['parts']])

    def test_xml_changes_are_checked_instead_of_trusting_the_plan(self):
        for mode in ('wire', 'cache', 'graphic', 'root', 'duplicate_reference', 'rotation', 'extra_property', 'hidden_hierarchy', 'cached_hierarchy', 'duplicate_flag', 'pin_geometry', 'pin_override'):
            with self.subTest(mode=mode):
                xml = self.xml_model(); inst = xml.find('.//PartInst')
                if mode == 'wire': xml.find('.//WireScalar/Defn').set('startX', '50')
                elif mode == 'cache': inst.find('Defn').set('libName', 'wrong.olb')
                elif mode == 'graphic': inst.find('GraphicName/Defn').set('name', 'wrong.Normal')
                elif mode == 'root': xml.find('Defn').set('rootName', 'MISSING')
                elif mode == 'duplicate_reference': xml.findall('.//PartInst/Reference/Defn')[1].set('name', 'J1')
                elif mode == 'rotation': inst.find('Defn').set('rotation', '90')
                elif mode == 'extra_property': sch.obj(inst, 'PartInstUserProp', name='PSpiceOnly', val='TRUE')
                elif mode == 'hidden_hierarchy': sch.obj(xml.find('Schematic/Page'), 'HierarchicalBlock')
                elif mode == 'cached_hierarchy': sch.obj(xml.find('.//LibPart'), 'HierarchicalBlock')
                elif mode == 'duplicate_flag': sch.obj(xml.find('.//SymbolPinScalar'), 'IsGlobal', val='1')
                elif mode == 'pin_geometry': xml.find('.//SymbolPinScalar/Defn').set('startX', 'broken')
                else: sch.obj(inst, 'PortInstScalar', position='99')
                with self.assertRaises(ValueError): sch.checked_xml(xml, self.profile, 10)

    def test_xml_branch_requires_a_junction_and_keeps_nc(self):
        self.plan['parts'].append(dict(refdes='R3', package='DEMO_TWO_PIN', page='PAGE1', at=[460, 400],
                                      value='1K', footprint='DEMO_R', basis='Synthetic branch',
                                      no_connect=[{'pin': '2', 'basis': 'Explicit test terminal'}]))
        self.plan['nets'][1]['nodes'].append(['R3', '1'])
        self.plan['nets'][1]['wires'].append([[440, 220], [440, 420]])
        xml = self.xml_model()
        result, plan, catalog = sch.checked_xml(xml, self.profile, 10)
        self.assertEqual(result['status'], 'checked_xml')
        self.assertEqual(plan['parts'][-1]['no_connect'][0]['pin'], '2')
        preview = ET.fromstring(sch.svg(plan, catalog, plan['pages'][0]))
        self.assertTrue(preview.findall('{http://www.w3.org/2000/svg}g/{http://www.w3.org/2000/svg}circle'))
        for wire in xml.findall('.//WireScalar'):
            for junction in wire.findall('Junction'): wire.remove(junction)
        with self.assertRaisesRegex(ValueError, 'Missing XML junction'): sch.checked_xml(xml, self.profile, 10)

    def test_headless_build_check_and_xml_preview_without_external_programs(self):
        with tempfile.TemporaryDirectory(prefix='headless schematic ') as temp:
            temp = Path(temp); build = temp / 'build'
            env = dict(os.environ, PATH='', DISPLAY='', WAYLAND_DISPLAY='', CDSROOT='', CDS_LIC_FILE='')
            args = [sys.executable, str(SKILL / 'scripts/schematic.py')]
            proc = subprocess.run(args + ['build', str(ASSETS / 'design-example.json'), '--library', str(ASSETS / 'library-example.xml'), '--profile', str(ASSETS / 'profile-example.json'), '--template', str(ASSETS / 'template-example.xml'), '--out', str(build)], env=env, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            result = json.loads(proc.stdout)
            self.assertEqual(result['execution'], 'headless'); self.assertEqual(result['native_execution'], 'not_requested')
            self.assertEqual(result['status'], 'checked_xml'); self.assertFalse((build / 'capture_bridge.tcl').exists())
            self.assertTrue((build / 'preview.html').is_file()); self.assertFalse(list(build.glob('*.dsn')))
            # XML alone supplies parts and geometry. The original plan/library are not inputs.
            xml = ET.parse(build / 'DEMO_DIVIDER.xml')
            xml.find('.//PartInst/PartValue/Defn').set('name', 'CHANGED & <XML>')
            actual = temp / 'edited.xml'; xml.write(actual, encoding='utf-8', xml_declaration=True)
            for command in ('check-xml', 'preview'):
                out = temp / command
                proc = subprocess.run(args + [command, str(actual), '--profile', str(ASSETS / 'profile-example.json'), '--out', str(out)], env=env, capture_output=True, text=True)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(json.loads(proc.stdout)['inputs_sha256']['xml'], sch.digest(actual))
            preview = (temp / 'preview/preview.html').read_text()
            self.assertIn('CHANGED &amp; &lt;XML&gt;', preview)
            self.assertNotIn('<script', preview)
            self.assertIn('CHANGED & <XML>', ''.join(ET.parse(temp / 'preview/PAGE1.svg').getroot().itertext()))

    def test_xml_preview_reports_geometry_errors(self):
        xml = self.xml_model()
        page = xml.find('Schematic/Page')
        wire = sch.obj(page, 'WireScalar', name='VOUT', startX=500, startY=220, endX=500, endY=300)
        sch.obj(wire, 'Alias', name='VOUT', locX=500, locY=220, rotation=0, color=0)
        sch.obj(wire, 'Junction', locX=500, locY=220)
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp); source = temp / 'input.xml'; ET.ElementTree(xml).write(source)
            proc = subprocess.run([sys.executable, str(SKILL / 'scripts/schematic.py'), 'preview', str(source), '--profile', str(ASSETS / 'profile-example.json'), '--out', str(temp / 'preview')], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 2, proc.stderr)
            result = json.loads(proc.stdout)
            self.assertEqual(result['status'], 'xml_errors')
            self.assertIn('dangling_wire', [d['code'] for d in result['diagnostics']])
            self.assertIn('xml_errors', (temp / 'preview/preview.html').read_text())

    def test_branch_junction_and_intentional_nc(self):
        self.plan['parts'].append(dict(refdes='R3', package='DEMO_TWO_PIN', page='PAGE1', at=[460, 400],
                                      value='1K', footprint='DEMO_R', basis='Synthetic branch',
                                      no_connect=[{'pin': '2', 'basis': 'Explicit test terminal'}]))
        net = self.plan['nets'][1]
        net['nodes'].append(['R3', '1']); net['wires'].append([[440, 220], [440, 420]])
        result, catalog = self.check(); self.assertEqual(result['status'], 'checked_model')
        xml = sch.design_xml(self.plan, self.library, catalog, self.template)
        self.assertTrue(any(d.get('locX') == '440' and d.get('locY') == '220' for d in xml.findall('.//Junction/Defn')))
        self.assertEqual(xml.find('.//PartInst/PortInstScalar/IsNoConnect/Defn').get('val'), '1')
        self.assertEqual(sch.expected_netlist(self.plan, catalog)['components']['R3']['pins'], ['1', '2'])

    def test_missing_pin_is_rejected(self):
        self.plan['nets'].pop()
        with self.assertRaisesRegex(ValueError, 'Every physical pin'): self.check()

    def test_duplicate_assignment_is_rejected(self):
        self.plan['nets'][1]['nodes'][0] = ['R1', '1']
        with self.assertRaisesRegex(ValueError, 'multiply assigned'): self.check()

    def test_nc_cannot_be_wired(self):
        self.plan['parts'][0]['no_connect'] = [{'pin': '1', 'basis': 'Synthetic NC'}]
        with self.assertRaisesRegex(ValueError, 'NC'): self.check()

    def test_library_nc_cannot_be_wired(self):
        self.library.find('.//SymbolPinScalar/IsNoConnect/Defn').set('val', '1')
        with self.assertRaisesRegex(ValueError, 'Library NC'): self.check()

    def test_disconnected_wire_is_error(self):
        self.plan['nets'][1]['wires'][0][1][0] -= 10
        result, _ = self.check()
        self.assertIn('disconnected_wire', [d['code'] for d in result['diagnostics']])

    def test_dangling_wire_is_error(self):
        self.plan['nets'][1]['wires'].append([[500, 220], [500, 300]])
        result, _ = self.check()
        self.assertIn('dangling_wire', [d['code'] for d in result['diagnostics']])

    def test_cross_net_contact_is_error(self):
        self.plan['nets'][1]['wires'] = [[[420, 220], [420, 520]], [[420, 520], [580, 520]], [[580, 520], [580, 220]]]
        result, _ = self.check()
        self.assertIn('net_contact', [d['code'] for d in result['diagnostics']])

    def test_unintended_pin_contact_is_error(self):
        self.plan['nets'][1]['wires'].append([[420, 220], [280, 220]])
        result, _ = self.check()
        self.assertIn('unintended_pin_contact', [d['code'] for d in result['diagnostics']])

    def test_output_conflict_is_error(self):
        self.profile['types'] = {'OUTPUT': 4}
        result, _ = self.check()
        self.assertIn('multiple_outputs', [d['code'] for d in result['diagnostics']])

    def test_input_without_driver_is_warning(self):
        self.profile['types'] = {'INPUT': 4}
        result, _ = self.check()
        self.assertEqual(result['status'], 'checked_model')
        self.assertTrue(all(d['severity'] == 'warning' for d in result['diagnostics']))
        self.assertEqual(len(result['diagnostics']), 3)

    def test_grid_page_and_rotation_limits(self):
        original = copy.deepcopy(self.plan)
        for update in ({'at': [301, 200]}, {'at': [990, 200]}, {'rotation': 90}):
            with self.subTest(update=update):
                self.plan = copy.deepcopy(original); self.plan['parts'][1].update(update)
                with self.assertRaises(ValueError): self.check()

    def test_cross_page_connections_are_not_flattened(self):
        self.plan['pages'].append({'name': 'PAGE2', 'size': [1000, 700]})
        self.plan['parts'][1]['page'] = 'PAGE2'
        with self.assertRaisesRegex(ValueError, 'Cross-page'): self.check()

    def test_common_rail_names(self):
        for name in ('+3V3', '3V3', '-12V'):
            self.plan['nets'][0]['name'] = name
            result, catalog = self.check()
            self.assertEqual(result['status'], 'checked_model')
            with tempfile.TemporaryDirectory() as temp:
                for filename, data in sch.pst(self.plan, catalog).items(): (Path(temp) / filename).write_text(data, encoding='utf-8')
                self.assertIn(name, pst.read_netlist(temp)['nets'])

    def test_hidden_global_or_unmapped_pin_is_rejected(self):
        for xpath, field, value in (('.//SymbolPinScalar/Defn', 'visible', '0'), ('.//SymbolPinScalar/IsGlobal/Defn', 'val', '1'), ('.//SymbolPinScalar/Defn', 'type', '99')):
            self.library = sch.read_xml(ASSETS / 'library-example.xml')
            self.library.find(xpath).set(field, value)
            with self.assertRaises(ValueError): self.check()

    def test_unmodeled_library_semantics_are_rejected(self):
        cases = [('Package', 'PackageUserProp', {'name': 'PSpiceOnly', 'val': 'TRUE'}),
                 ('NormalView', 'SymbolUserProp', {'name': 'PSpiceOnly', 'val': 'TRUE'}),
                 ('PhysicalPart', 'PinShared', {'shared': '1', 'position': '0'}),
                 ('PhysicalPart', 'PinSwap', {'swapid': '1', 'position': '0'}),
                 ('NormalView', 'ContentsViewName', {'name': 'CHILD'})]
        for parent, tag, attrs in cases:
            with self.subTest(tag=tag):
                self.library = sch.read_xml(ASSETS / 'library-example.xml')
                sch.obj(self.library.find('.//' + parent), tag, **attrs)
                with self.assertRaisesRegex(ValueError, 'property|review'): self.check()

    def test_duplicate_or_nonprimitive_template_is_rejected(self):
        _, catalog = self.check()
        for mode in ('cache', 'nonprimitive', 'part', 'extra_schematic'):
            with self.subTest(mode=mode):
                template = copy.deepcopy(self.template)
                if mode == 'cache': sch.obj(template, 'Cache')
                elif mode == 'nonprimitive': sch.obj(sch.obj(template, 'DefaultValues'), 'DefaultPlacedInstIsPrimitive', val=0)
                elif mode == 'part': sch.obj(template.find('Schematic/Page'), 'PartInst')
                else: sch.obj(template, 'Schematic', name='EXTRA')
                with self.assertRaises(ValueError): sch.design_xml(self.plan, self.library, catalog, template)

    def test_duplicate_json_and_encoded_dtd_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'input'
            path.write_text('{"name":"A","name":"B"}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Duplicate JSON'): sch.read_json(path)
            for encoding in ('utf-8', 'utf-16'):
                path.write_bytes(('<?xml version="1.0" encoding="' + encoding + '"?><!DOCTYPE Design [<!ENTITY x "hello">]><Design>&x;</Design>').encode(encoding))
                with self.assertRaisesRegex(ValueError, 'DTD'): sch.read_xml(path)

    def test_xml_forbidden_characters_are_rejected_before_output(self):
        with tempfile.TemporaryDirectory() as temp:
            for i, char in enumerate(('\ufffe', '\uffff', '\ud800', '\x01')):
                self.plan['parts'][1]['value'] = '10K' + char
                plan = Path(temp) / 'plan.json'; plan.write_text(json.dumps(self.plan), encoding='utf-8')
                out = Path(temp) / str(i); proc = self.command('build', out, ['--template', ASSETS / 'template-example.xml'], plan=plan)
                self.assertEqual(proc.returncode, 2); self.assertFalse(out.exists())
                self.assertEqual(json.loads(proc.stderr)['status'], 'failed')

    def test_xml_escaping_keeps_values_and_valid_output(self):
        self.plan['parts'][1]['value'] = '10K & <test> "quoted"'
        _, catalog = self.check(); xml = sch.design_xml(self.plan, self.library, catalog, self.template)
        rebuilt = ET.fromstring(ET.tostring(xml))
        self.assertEqual(rebuilt.findall('.//PartInst/PartValue/Defn')[1].get('name'), self.plan['parts'][1]['value'])

    def test_changed_netlist_connectivity_and_footprint_fail(self):
        _, catalog = self.check(); expected = sch.expected_netlist(self.plan, catalog)
        for mode in ('swap', 'missing_pin', 'footprint', 'extra_part', 'duplicate_node'):
            with self.subTest(mode=mode):
                actual = copy.deepcopy(expected)
                if mode == 'swap': actual['nets']['VIN']['nodes'][0]['pin'] = '2'
                elif mode == 'missing_pin': actual['components']['R1']['pins'].pop()
                elif mode == 'footprint': actual['components']['R1']['symbol'] = 'OTHER'
                elif mode == 'extra_part': actual['components']['R3'] = actual['components']['R1']
                else: actual['nets']['VIN']['nodes'].append(actual['nets']['VIN']['nodes'][0])
                with self.assertRaises(ValueError): sch.verify_netlist(expected, actual)

    def test_malformed_actual_returns_structured_failure(self):
        _, catalog = self.check(); actual = sch.expected_netlist(self.plan, catalog)
        with tempfile.TemporaryDirectory() as temp:
            actual['components']['R1'] = []
            snapshot = Path(temp) / 'actual.json'; sch.write_json(snapshot, actual)
            proc = self.command('verify-netlist', Path(temp) / 'out', ['--actual', snapshot])
            self.assertEqual(proc.returncode, 2); self.assertEqual(json.loads(proc.stderr)['status'], 'failed')

    def test_failed_model_does_not_generate_import_artifacts(self):
        self.plan['nets'][1]['wires'][0][1][0] -= 10
        with tempfile.TemporaryDirectory() as temp:
            plan = Path(temp) / 'plan.json'; sch.write_json(plan, self.plan); out = Path(temp) / 'out'
            proc = self.command('build', out, ['--template', ASSETS / 'template-example.xml'], plan)
            self.assertEqual(proc.returncode, 2)
            self.assertFalse((out / 'model-netlist').exists()); self.assertFalse(list(out.glob('*.xml')))
            self.assertEqual(json.loads((out / 'result.json').read_text())['status'], 'model_errors')

    def test_job_cannot_overwrite_previous_output(self):
        with tempfile.TemporaryDirectory() as temp:
            marker = Path(temp) / 'keep'; marker.write_text('original')
            proc = self.command('check', Path(temp))
            self.assertEqual(proc.returncode, 2); self.assertEqual(marker.read_text(), 'original')

    def test_binary_dsn_is_not_parsed_as_xml(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'design.dsn'; path.write_bytes(bytes.fromhex('D0CF11E0A1B11AE1'))
            with self.assertRaisesRegex(ValueError, 'exported XML'): sch.read_xml(path)

    def test_drc_report_never_infers_completion(self):
        with tempfile.TemporaryDirectory() as temp:
            report = Path(temp) / 'report.drc'
            for i, data in enumerate(('ERROR(ORCAP-1234): test\nWARNING(ORCAP-2222): review', '0 errors', 'unrecognized localized report')):
                report.write_text(data, encoding='utf-8')
                proc = subprocess.run([sys.executable, str(SKILL / 'scripts/schematic.py'), 'drc-report', str(report), '--out', str(Path(temp) / str(i))], capture_output=True, text=True)
                self.assertEqual(proc.returncode, 0); result = json.loads(proc.stdout)
                self.assertFalse(result['completion_verified']); self.assertFalse(result['native_capture_verified'])
                if i == 0: self.assertEqual(len(result['findings']), 2)
            report.write_text('')
            proc = subprocess.run([sys.executable, str(SKILL / 'scripts/schematic.py'), 'drc-report', str(report), '--out', str(Path(temp) / 'empty')], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 2)

    def test_installed_skill_runs_without_repository_imports(self):
        with tempfile.TemporaryDirectory(prefix='schematic installed ') as temp:
            home = Path(temp) / 'home'
            subprocess.run([sys.executable, str(ROOT / 'scripts/install.py'), '--home', str(home), '--host', 'codex'], check=True, stdout=subprocess.DEVNULL)
            skill = home / '.codex/skills/orcad-schematic'; assets = skill / 'assets'; out = Path(temp) / 'job'
            subprocess.run([sys.executable, str(skill / 'scripts/schematic.py'), 'build', str(assets / 'design-example.json'), '--library', str(assets / 'library-example.xml'), '--profile', str(assets / 'profile-example.json'), '--template', str(assets / 'template-example.xml'), '--out', str(out)], cwd=temp, check=True, stdout=subprocess.DEVNULL)
            self.assertEqual(ET.parse(out / 'DEMO_DIVIDER.xml').getroot().tag, 'Design')
            for rel, expected in json.loads((out / 'result.json').read_text())['outputs_sha256'].items(): self.assertEqual(sch.digest(out / rel), expected)
            for command in ('check-xml', 'preview'):
                output = Path(temp) / command
                proc = subprocess.run([sys.executable, str(skill / 'scripts/schematic.py'), command, str(out / 'DEMO_DIVIDER.xml'), '--profile', str(assets / 'profile-example.json'), '--out', str(output)], cwd=temp, check=True, capture_output=True, text=True)
                self.assertEqual(json.loads(proc.stdout)['status'], 'checked_xml')
            self.assertTrue((Path(temp) / 'preview/preview.html').is_file())

    @unittest.skipUnless(shutil.which('tclsh'), 'Tcl interpreter is optional')
    def test_tcl_bridge_rejects_missing_runtime_and_aliased_outputs(self):
        with tempfile.TemporaryDirectory(prefix='capture bridge ') as temp:
            script = Path(temp) / 'test.tcl'
            # Use a separate Tcl process: no Capture execution or loaded database.
            source = (SKILL / 'scripts/capture_bridge.tcl').as_posix()
            script.write_text('source {' + source + '}\n'
                              'if {![catch {agentSchematic::importDesign missing.xml new.dsn out.log out.tcl} msg]} {exit 2}\n'
                              'if {![string match {*unavailable*} $msg]} {exit 3}\n'
                              'proc XMATIC_XML2DSN {args} {error "Should not execute"}\n'
                              'if {![catch {agentSchematic::importDesign same.xml SAME.XML out.log out.tcl} msg]} {exit 4}\n'
                              'if {![string match {*distinct*} $msg]} {exit 5}\n', encoding='utf-8')
            subprocess.run(['tclsh', str(script)], cwd=temp, check=True, capture_output=True, text=True)

    @unittest.skipUnless(shutil.which('tclsh'), 'Tcl interpreter is optional')
    def test_tcl_probe_reads_global_enums(self):
        with tempfile.TemporaryDirectory() as temp:
            script = Path(temp) / 'test.tcl'
            source = (SKILL / 'scripts/capture_bridge.tcl').as_posix()
            script.write_text('source {' + source + '}\n'
                              'set ::DboValue_PASSIVE 4\nset ::DboValue_LABEL text\n'
                              'agentSchematic::probe probe\n', encoding='utf-8')
            subprocess.run(['tclsh', str(script)], cwd=temp, check=True, capture_output=True, text=True)
            self.assertEqual((Path(temp) / 'probe/enum-dump.tsv').read_text(), 'DboValue_PASSIVE\t4\n')

    @unittest.skipUnless(shutil.which('tclsh'), 'Tcl interpreter is optional')
    def test_tcl_native_failure_and_rootless_export_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            source = (SKILL / 'scripts/capture_bridge.tcl').as_posix()
            script = Path(temp) / 'test.tcl'
            script.write_text('source {' + source + '}\n' + '''
proc failedState {method} {return 1}
proc XMATIC_XML2DSN {args} {return failedState}
close [open input.xml w]
if {![catch {agentSchematic::importDesign input.xml output.dsn import.log recipe.tcl ROOT} msg]} {exit 2}
if {![string match {*failed to import*} $msg]} {exit 3}
proc XMATIC_DSN2XML {args} {error "Exporter must not run on a rootless design"}
proc DboTclHelper_sCreateSession {} {return mockSession}
proc DboTclHelper_sDeleteSession {session} {set ::released 1}
proc DboTclHelper_sMakeCString {value} {return $value}
proc DboState {} {return goodState}
proc goodState {method} {return 0}
proc mockSession {method args} {return mockDesign}
proc mockDesign {method args} {return NULL}
close [open input.dsn w]
close [open dsn.xsd w]
set ::released 0
if {![catch {agentSchematic::exportDesign input.dsn output.xml dsn.xsd export.log} msg]} {exit 4}
if {![string match {*no root schematic*} $msg]} {error $msg}
if {!$::released || [file exists output.xml]} {exit 5}
''', encoding='utf-8')
            subprocess.run(['tclsh', str(script)], cwd=temp, check=True, capture_output=True, text=True)


if __name__ == '__main__':
    unittest.main()
