import copy,json
from pathlib import Path
import tempfile,unittest
from opencaliber import agent_server as store
from opencaliber.agent_engine import DEFAULT_CONFIG
from opencaliber.contract_cases import validate_case,preview,save,list_cases

class ContractCaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.previous=store.DB;store.DB=Path(self.temp.name)/'workspace.sqlite3';store.initialize()
        self.case={'id':'MY-001','name':'Read a ticket','trace':{'task':{'goal':'Read tickets','allowed_tools':['database.read'],'allowed_resources':['tickets']},'actions':[{'id':'read-1','tool':'database.read','resource':'tickets','arguments':{'records':1}}]},'expected':{'assessment':'clear','required_codes':[]},'config_patch':{}}
    def tearDown(self):store.DB=self.previous;self.temp.cleanup()
    def save(self):return save(self.case,store.connect,{'OC-001'},DEFAULT_CONFIG,store.timestamp)
    def test_save_survives_initialize_and_is_in_suite(self):
        self.assertTrue(self.save()['preview']['passed']);store.initialize()
        self.assertEqual(list_cases(store.connect)[0]['id'],'MY-001')
        self.assertEqual(len(store.cases()['cases']),71)
        report=store.benchmark(DEFAULT_CONFIG,['MY-001']);self.assertEqual(report['passed'],1)
    def test_duplicate_and_included_ids_rejected(self):
        self.save()
        with self.assertRaises(ValueError):self.save()
        self.case['id']='OC-001'
        with self.assertRaises(ValueError):self.save()
    def test_preview_does_not_save(self):
        self.assertTrue(preview(self.case,DEFAULT_CONFIG)['passed']);self.assertEqual(list_cases(store.connect),[])
    def test_mismatch_can_be_saved(self):
        self.case['expected']={'assessment':'violation','required_codes':['FILE_BOUNDARY']}
        self.assertFalse(self.save()['preview']['passed'])
        self.assertEqual(store.benchmark(DEFAULT_CONFIG,['MY-001'])['failed'],1)
    def test_override_controls_result(self):
        self.case['config_patch']={'max_records':1};self.case['trace']['actions'][0]['arguments']['records']=2
        self.case['expected']={'assessment':'violation','required_codes':['RECORD_BUDGET']}
        self.assertTrue(self.save()['preview']['passed'])
    def test_invalid_fields_are_rejected(self):
        bad=[]
        for field,value in [('id','../bad'),('name',''),('trace',{}),('expected',{'assessment':'unsafe','required_codes':[]}),('config_patch',{'unknown':True}),('config_patch',{'max_records':0})]:
            c=copy.deepcopy(self.case);c[field]=value;bad.append(c)
        c=copy.deepcopy(self.case);c['expected']['required_codes']=['FILE_BOUNDARY'];bad.append(c)
        c=copy.deepcopy(self.case);c['extra']=True;bad.append(c)
        for c in bad:
            with self.subTest(case=c),self.assertRaises(ValueError):validate_case(c)
    def test_required_codes_are_subset_not_exact(self):
        self.case['trace']['actions'][0]['arguments']['records']=2000
        self.case['expected']={'assessment':'violation','required_codes':[]}
        self.assertTrue(preview(self.case,DEFAULT_CONFIG)['passed'])
    def test_builtin_file_not_modified(self):
        before=(store.ROOT/'data/agent_cases.json').read_bytes();self.save()
        self.assertEqual(before,(store.ROOT/'data/agent_cases.json').read_bytes())

if __name__=='__main__':unittest.main()
