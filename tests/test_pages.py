from tools.build_agent_library import AGENTS
import io
import json
from html.parser import HTMLParser
from pathlib import Path
import tempfile
import unittest
from urllib.parse import urlsplit,unquote
import zipfile
from tools.build_pages import ROOT,build

class Links(HTMLParser):
    def __init__(self):super().__init__();self.urls=[]
    def handle_starttag(self,tag,attrs):
        self.urls.extend(value for key,value in attrs if key in ('href','src','poster') and value)

class PagesTests(unittest.TestCase):
    def test_root_and_project_sites(self):
        (ROOT/'dist').mkdir(exist_ok=True)
        for base in ('','/opencaliber'):
            with self.subTest(base=base),tempfile.TemporaryDirectory(dir=ROOT/'dist') as folder:
                site=build(Path(folder)/'site',base)
                for html in site.rglob('*.html'):
                    parser=Links();parser.feed(html.read_text(encoding='utf-8'))
                    for url in parser.urls:
                        if url.startswith('#') or urlsplit(url).scheme:continue
                        path=unquote(urlsplit(url).path)
                        self.assertTrue(path.startswith(base+'/'),url)
                        file=site/path[len(base)+1:]
                        if file.is_dir():file=file/'index.html'
                        self.assertTrue(file.is_file(),(html,url))
                        self.assertNotIn('/api/',path)
                catalog=json.loads((site/'agents.json').read_text())
                self.assertEqual(len(catalog),len(AGENTS))
                for agent in catalog:
                    pack=site/agent['download'][len(base)+1:]
                    with zipfile.ZipFile(pack) as z:self.assertIsNone(z.testzip())
                js=(site/'agents.js').read_text(encoding='utf-8')
                self.assertIn(json.dumps(base+'/agents.json'),js)
                self.assertNotIn("fetch('agents.json'",js)
                with zipfile.ZipFile(site/'downloads/opencaliber.zip') as z:
                    self.assertIn('LICENSE',z.namelist())
                    self.assertIn('web/console.html',z.namelist())
                    self.assertFalse(any('sqlite' in n or '.env'==Path(n).name for n in z.namelist()))
                self.assertFalse((site/'console.js').exists())
                self.assertTrue((site/'console/index.html').exists())
                self.assertTrue((site/'.nojekyll').exists())
    def test_release_links_and_persistent_snapshot(self):
        from opencaliber.download_ledger import empty,merge
        from tools.manage_releases import catalog
        tag='v'+catalog()[0]['version']
        snapshot=merge(empty('arun1011/opencaliber'),[{'tag_name':tag,'assets':[{'id':123,'name':'opencaliber.zip','download_count':42}]}],'arun1011/opencaliber',[])
        (ROOT/'dist').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT/'dist') as folder:
            prior=Path(folder)/'counts.json';prior.write_text(json.dumps(snapshot))
            for name in ('first','redeployed'):
                site=build(Path(folder)/name,'',tag,'arun1011/opencaliber',prior)
                self.assertIn(f'https://github.com/arun1011/opencaliber/releases/download/{tag}/opencaliber.zip',(site/'index.html').read_text(encoding='utf-8'))
                self.assertEqual(json.loads((site/'download-counts.json').read_text())['total_downloads'],42)
                self.assertTrue(all(a['download'].startswith(f'https://github.com/arun1011/opencaliber/releases/download/{tag}/') for a in json.loads((site/'agents.json').read_text())))

    def test_reject_invalid_output_and_base_path(self):
        for base in ('https://example.com','/../private','//example.com'):
            with self.assertRaises(ValueError):build(ROOT/'dist/invalid',base)
        with self.assertRaises(ValueError):build(ROOT)

if __name__=='__main__':unittest.main()
