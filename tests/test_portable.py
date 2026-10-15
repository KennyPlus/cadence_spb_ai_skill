import copy,importlib.util,json,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def module(name,skill,script):
 s=importlib.util.spec_from_file_location(name,ROOT/'skills'/skill/'scripts'/script);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
pad=module('portable_pad','allegro-padstack','padstack.py');pkg=module('portable_package','allegro-package','package.py');lib=module('portable_lib','allegro-library','library.py');sym=module('portable_symbol','orcad-symbol','symbol.py')
class PortableTests(unittest.TestCase):
 def test_pad_offsets_and_precision(self):
  s=json.loads((ROOT/'skills/allegro-padstack/assets/smd-example.json').read_text());s['measurement']={'basis':'Synthetic datum','layer_centers':{'begin':[10,20],'mask_top':[10.025,20],'paste_top':[10,19.975]}}
  before=copy.deepcopy(s);n,t=pad.normalize_measurement(s);pad.validate(n);self.assertEqual(s,before)
  self.assertEqual(n['pads']['mask_top']['offset'],[.025,0]);self.assertIn('(0.0;-0.025)',pad.pxml(n))
  with self.assertRaises(ValueError):pad.replay(n)
  s['measurement']['layer_centers']['paste_top'][0]=10.0005
  with self.assertRaises(ValueError):pad.validate(pad.normalize_measurement(s)[0])
 def test_package_rotated_shift(self):
  s=json.loads((ROOT/'skills/allegro-package/assets/smd2-example.json').read_text());s['measurement']={'basis':'Synthetic body','body_bounds':{'min':[9,19],'max':[11,21]},'pad_origin_shifts':{'example_pad':[.1,.2]}}
  s['pins'][0]['xy']=[9.2,20];s['pins'][1]['xy']=[10.8,20];n,t=pkg.normalize_measurement(s)
  self.assertEqual([p['xy'] for p in n['pins']],[[-.7,.2],[.6,.1]])
 def test_shape_center_and_flash_frame(self):
  s=json.loads((ROOT/'skills/allegro-library/assets/shape-example.json').read_text());n,t=lib.normalize_measurement(s);self.assertEqual(t['source_center'],[2,1.5]);lib.design_records(n)
  s['type']='flash'
  with self.assertRaises(ValueError):lib.normalize_measurement(s)
 def test_capture_power_and_changed_flags(self):
  s=json.loads((ROOT/'skills/orcad-symbol/assets/power-terminals-example.json').read_text());p=json.loads((ROOT/'skills/orcad-symbol/assets/observed-profile.json').read_text());xml=sym.build(s,p);sym.verify(s,p,xml)
  xml.find('.//IsGlobal/Defn').set('val','1')
  with self.assertRaises(ValueError):sym.verify(s,p,xml)
 def test_installed_skill_cli_without_reference_files(self):
  with tempfile.TemporaryDirectory(prefix='portable skills ') as d:
   home=Path(d)/'home';subprocess.run([sys.executable,str(ROOT/'scripts/install.py'),'--home',str(home),'--host','codex'],stdout=subprocess.DEVNULL,check=True)
   root=home/'.codex/skills'
   jobs=[('allegro-padstack','padstack.py','build','smd-example.json',[]),('allegro-library','library.py','design','shape-example.json',[]),('orcad-symbol','symbol.py','build','power-terminals-example.json',['--profile',str(root/'orcad-symbol/assets/observed-profile.json')])]
   for skill,script,command,example,extra in jobs:
    subprocess.run([sys.executable,str(root/skill/'scripts'/script),command,str(root/skill/'assets'/example),'--out',str(Path(d)/skill)]+extra,cwd=d,stdout=subprocess.DEVNULL,check=True)
if __name__=='__main__':unittest.main()
