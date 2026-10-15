import importlib.util
from pathlib import Path
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('installer',ROOT/'scripts/install.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class InstallerTests(unittest.TestCase):
 def test_all_hosts_readback_and_idempotence(self):
  with tempfile.TemporaryDirectory(prefix='skill install ') as d:
   home=Path(d)/'user'
   result=m.install(ROOT/'skills',home,tuple(m.HOSTS))
   self.assertEqual(len(result['skills']),len(m.SKILLS)*len(m.HOSTS))
   for host in m.HOSTS:
    for name in m.SKILLS:self.assertEqual(m.inventory(home/m.HOSTS[host]/'skills'/name),m.payload(ROOT/'skills',name))
   self.assertTrue(all(x['action']=='unchanged' for x in m.install(ROOT/'skills',home,tuple(m.HOSTS))['skills']))
 def test_dry_run_does_not_create_home(self):
  with tempfile.TemporaryDirectory() as d:
   home=Path(d)/'new';m.install(ROOT/'skills',home,('codex',),dry_run=True);self.assertFalse(home.exists())
 def test_conflict_preflight_backup_replace(self):
  with tempfile.TemporaryDirectory() as d:
   home=Path(d);m.install(ROOT/'skills',home,('codex',))
   target=home/'.codex/skills/orcad-symbol/SKILL.md';target.write_text('user modified')
   with self.assertRaises(ValueError):m.install(ROOT/'skills',home,('codex',))
   self.assertEqual(target.read_text(),'user modified')
   result=m.install(ROOT/'skills',home,('codex',),replace=True)
   row=next(x for x in result['skills'] if x['skill']=='orcad-symbol')
   self.assertEqual((Path(row['backup'])/'SKILL.md').read_text(),'user modified')
   self.assertEqual(m.inventory(target.parent),m.payload(ROOT/'skills','orcad-symbol'))
 def test_custom_codex_home(self):
  with tempfile.TemporaryDirectory() as d:
   custom=Path(d)/'custom';m.install(ROOT/'skills',Path(d)/'user',('codex',),codex_home=custom)
   self.assertTrue((custom/'skills/orcad-symbol/SKILL.md').is_file())
 def test_copy_failure_restores_old_skill(self):
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as d:
   home=Path(d);m.install(ROOT/'skills',home,('codex',));target=home/'.codex/skills/allegro-padstack/SKILL.md';target.write_text('keep')
   with patch.object(m.shutil,'copy2',side_effect=OSError('disk failure')):
    with self.assertRaises(OSError):m.install(ROOT/'skills',home,('codex',),replace=True)
   self.assertEqual(target.read_text(),'keep')
if __name__=='__main__':unittest.main()
