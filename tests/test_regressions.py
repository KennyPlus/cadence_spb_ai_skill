"""Offline failure cases using synthetic data; no Cadence installation required."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


installer = load('regression_installer', 'scripts/install.py')
package = load('regression_package', 'skills/allegro-package/scripts/package.py')
padstack = load('regression_padstack', 'skills/allegro-padstack/scripts/padstack.py')
symbol = load('regression_symbol', 'skills/orcad-symbol/scripts/symbol.py')


def example(skill, filename):
    return json.loads((ROOT / 'skills' / skill / 'assets' / filename).read_text(encoding='utf-8'))


# Synthetic report for the published smd2 example, including pin and text extents.
PACKAGE_REPORT = '''UNITS|millimeters|3
TYPE|PACKAGE
PIN|1|EXAMPLE_PAD|-0.8|0|0|nil|nil|-0.9|-0.3|-0.7|0.3
PIN|2|EXAMPLE_PAD|0.8|0|90|nil|nil|0.5|-0.1|1.1|0.1
LINE|PACKAGE GEOMETRY/ASSEMBLY_TOP|0.1|-0.5|-0.4|0.5|-0.4
LINE|PACKAGE GEOMETRY/ASSEMBLY_TOP|0.1|0.5|-0.4|0.5|0.4
LINE|PACKAGE GEOMETRY/ASSEMBLY_TOP|0.1|0.5|0.4|-0.5|0.4
LINE|PACKAGE GEOMETRY/ASSEMBLY_TOP|0.1|-0.5|0.4|-0.5|-0.4
LINE|PACKAGE GEOMETRY/SILKSCREEN_TOP|0.1|-0.5|-0.55|0.5|-0.55
LINE|PACKAGE GEOMETRY/SILKSCREEN_TOP|0.1|-0.5|0.55|0.5|0.55
RECT|PACKAGE GEOMETRY/PLACE_BOUND_TOP|-1.3|-0.7|1.3|0.7
HEIGHT|0.8
TEXT|REF DES/SILKSCREEN_TOP|R*|0|1.3|0|CENTER|nil
TEXTBOX|REF DES/SILKSCREEN_TOP|-0.4|1|0.4|1.6
FONT|0.4|0.6|0.8|0.1|0.1
TEXT|REF DES/ASSEMBLY_TOP|R*|0|0|0|CENTER|nil
TEXTBOX|REF DES/ASSEMBLY_TOP|-0.4|-0.3|0.4|0.3
FONT|0.4|0.6|0.8|0.1|0.1
END
'''


class InstallerRegressionTests(unittest.TestCase):
    def test_aliased_host_destinations_install_once(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            for repeat in (False, True):
                result = installer.install(ROOT / 'skills', home, ('codex', 'claude'),
                                           codex_home=home / '.claude')
                self.assertEqual(len(result['skills']), len(installer.SKILLS))
                self.assertTrue(all(row['verified'] for row in result['skills']))
                if repeat:
                    self.assertTrue(all(row['action'] == 'unchanged' for row in result['skills']))
            for name in installer.SKILLS:
                self.assertEqual(installer.inventory(home / '.claude' / 'skills' / name),
                                 installer.payload(ROOT / 'skills', name))

    def test_linked_skill_requires_replacement_and_preserves_link_target(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            name = installer.SKILLS[0]
            target = home / '.codex' / 'skills' / name
            target.parent.mkdir(parents=True)
            source = ROOT / 'skills' / name
            before = installer.payload(ROOT / 'skills', name)
            try:
                target.symlink_to(source, target_is_directory=True)
            except (OSError, NotImplementedError) as error:
                self.skipTest('Directory symlinks unavailable: ' + str(error))
            with self.assertRaises(ValueError):
                installer.install(ROOT / 'skills', home, ('codex',))
            self.assertTrue(target.is_symlink())
            result = installer.install(ROOT / 'skills', home, ('codex',), replace=True)
            row = next(row for row in result['skills'] if row['skill'] == name)
            self.assertFalse(target.is_symlink())
            self.assertTrue(Path(row['backup']).is_symlink())
            self.assertEqual(installer.inventory(target), before)
            self.assertEqual(installer.payload(ROOT / 'skills', name), before)

    def test_failed_final_readback_restores_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            installer.install(ROOT / 'skills', home, ('codex',))
            destination = home / '.codex' / 'skills' / installer.SKILLS[0]
            entrypoint = destination / 'SKILL.md'
            entrypoint.write_text('keep my version', encoding='utf-8')
            real_inventory = installer.inventory

            def fail_installed_readback(path):
                if path == destination and entrypoint.read_text(encoding='utf-8') != 'keep my version':
                    raise OSError('readback failed')
                return real_inventory(path)

            with patch.object(installer, 'inventory', side_effect=fail_installed_readback):
                with self.assertRaises(OSError):
                    installer.install(ROOT / 'skills', home, ('codex',), replace=True)
            self.assertEqual(entrypoint.read_text(encoding='utf-8'), 'keep my version')


class PackageReadbackRegressionTests(unittest.TestCase):
    def verify_report(self, report):
        spec = example('allegro-package', 'smd2-example.json')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'readback.txt'
            path.write_text(report, encoding='utf-8')
            return package.verify(spec, path)

    def test_synthetic_report_is_valid(self):
        self.assertTrue(self.verify_report(PACKAGE_REPORT)['geometry_verified'])

    def test_nonfinite_pin_bounds_are_rejected(self):
        for value in ('nan', 'inf', '-inf'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.verify_report(PACKAGE_REPORT.replace('|-0.9|-0.3|-0.7|0.3', '|' + '|'.join([value] * 4)))

    def test_reversed_pin_bounds_are_rejected(self):
        with self.assertRaises(ValueError):
            self.verify_report(PACKAGE_REPORT.replace('|-0.9|-0.3|-0.7|0.3', '|-0.7|-0.3|-0.9|0.3'))

    def test_nonfinite_text_bounds_are_rejected(self):
        with self.assertRaises(ValueError):
            self.verify_report(PACKAGE_REPORT.replace('|-0.4|1|0.4|1.6', '|nan|nan|nan|nan'))

    def test_text_bounds_must_match_text_layers(self):
        for layer in ('IGNORED_LAYER', 'REF DES/ASSEMBLY_TOP'):
            with self.subTest(layer=layer), self.assertRaises(ValueError):
                self.verify_report(PACKAGE_REPORT.replace('TEXTBOX|REF DES/SILKSCREEN_TOP|', 'TEXTBOX|' + layer + '|'))

    def test_malformed_records_fail_with_validation_errors(self):
        for before, after in (
                ('TYPE|PACKAGE', 'TYPE'),
                ('|-0.9|-0.3|-0.7|0.3', '|-0.9'),
                ('|-0.4|1|0.4|1.6', '|-0.4|1|0.4|1.6|999')):
            with self.subTest(after=after), self.assertRaises(ValueError):
                self.verify_report(PACKAGE_REPORT.replace(before, after))

    def test_silkscreen_collision_still_fails(self):
        with self.assertRaises(ValueError):
            self.verify_report(PACKAGE_REPORT.replace('|-0.4|1|0.4|1.6', '|-0.9|-0.3|-0.7|0.3'))


class XmlRegressionTests(unittest.TestCase):
    def test_dtd_rejected_for_all_supported_encodings(self):
        xml = '<!DOCTYPE Lib [<!ENTITY sample "expanded">]><Lib>&sample;</Lib>'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'input.xml'
            for encoding in ('utf-8', 'utf-16', 'utf-16-le', 'utf-16-be'):
                with self.subTest(encoding=encoding):
                    path.write_bytes(xml.encode(encoding))
                    with self.assertRaises(ValueError):
                        symbol.read_xml(path)

    def test_utf16_xml_without_dtd_remains_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'input.xml'
            path.write_bytes('<Lib><Defn name="example.olb"/></Lib>'.encode('utf-16'))
            self.assertEqual(symbol.read_xml(path).tag, 'Lib')


class NativeFailureRegressionTests(unittest.TestCase):
    def test_pad_report_timeout_cannot_be_verified_even_with_zero_exit(self):
        spec = example('allegro-padstack', 'smd-example.json')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cadence = root / 'cadence'
            binary = cadence / 'tools.lnx86' / 'bin' / 'padstack_editor.exe'
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b'synthetic executable identity')
            out = root / 'job'
            args = SimpleNamespace(execute=True, cadence_root=cadence, backend='replay',
                                   replay_mask_column='Pad', compat_172=False, starter_file=None,
                                   display='none', timeout=1, cleanup_mainwin_exit=False)

            def fake_run(command, cwd, env, seconds, log, completed_journal=None):
                is_report = Path(command[0]).name == 'report'
                if not is_report:
                    (cwd / (spec['name'] + '.pad')).write_bytes(b'synthetic PAD')
                return {'command': command, 'returncode': 0, 'timed_out': is_report,
                        'mainwin_exit_cleanup': False}

            with patch.object(padstack, 'run_process', side_effect=fake_run), \
                    patch.object(padstack, 'verify', return_value={'geometry_verified': True}) as verify:
                result = padstack.build(spec, out, args)
            self.assertEqual(result['status'], 'failed')
            verify.assert_not_called()


class EncodingRegressionTests(unittest.TestCase):
    @unittest.skipIf(os.name == 'nt', 'Uses a POSIX ASCII locale to exercise non-UTF-8 defaults')
    def test_non_ascii_specs_work_with_ascii_locale(self):
        env = dict(os.environ, LC_ALL='C', PYTHONUTF8='0', PYTHONCOERCECLOCALE='0',
                   PYTHONIOENCODING='utf-8')
        jobs = (
            ('allegro-padstack', 'padstack.py', 'smd-example.json', 'build', 'spec.json'),
            ('allegro-package', 'package.py', 'smd2-example.json', 'build', 'spec.json'),
            ('allegro-library', 'library.py', 'shape-example.json', 'design', 'design.json'),
        )
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            pad = base / 'example.pad'
            pad.write_bytes(b'synthetic PAD for generation only')
            for skill, script, filename, command, normalized in jobs:
                for escaped in (True, False):
                    with self.subTest(skill=skill, escaped=escaped):
                        spec = example(skill, filename)
                        spec['sources'][0]['basis'] = '尺寸依据'
                        if skill == 'allegro-package':
                            spec['padstacks']['example_pad'] = str(pad)
                        source = base / 'spec.json'
                        source.write_text(json.dumps(spec, ensure_ascii=escaped), encoding='utf-8')
                        out = base / (skill + str(escaped))
                        process = subprocess.run(
                            [sys.executable, str(ROOT / 'skills' / skill / 'scripts' / script),
                             command, str(source), '--out', str(out)],
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding='utf-8', timeout=15)
                        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                        saved = json.loads((out / normalized).read_text(encoding='utf-8'))
                        self.assertEqual(saved['sources'][0]['basis'], '尺寸依据')


if __name__ == '__main__':
    unittest.main()
