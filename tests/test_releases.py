import io,json,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
from tools.manage_releases import create,validate,core_hash,version_tuple

class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent);self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'web').mkdir();(self.root/'data').mkdir();(self.root/'opencaliber').mkdir()
        (self.root/'data/agent_cases.json').write_text('{}');(self.root/'opencaliber/core.py').write_text('value=1\n')
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as z:z.writestr('run.py','print("runtime")')
        for name,value in [('tools.build_agent_library.main',None),('tools.build_public_guide.build',None),('opencaliber.local_package.build_package',stream.getvalue())]:
            task=patch(name,return_value=value);task.start();self.addCleanup(task.stop)
    def release(self,version='0.6.0'):return create(version,'Connected agents',['Added monitoring.'],'2026-11-12',self.root)
    def test_archive_contains_notes_and_checksum_validates(self):
        row=self.release();self.assertEqual(validate(self.root)[0]['version'],'0.6.0')
        with zipfile.ZipFile(self.root/'web'/row['download']) as z:self.assertIn('Added monitoring.',z.read('RELEASE_NOTES.md').decode())
    def test_same_or_older_version_cannot_replace_archive(self):
        row=self.release();path=self.root/'web'/row['download'];before=path.read_bytes()
        for version in ('0.6.0','0.5.0'):
            with self.assertRaises(ValueError):self.release(version)
        self.assertEqual(path.read_bytes(),before)
    def test_second_release_retains_first_download(self):
        row=self.release();before=(self.root/'web'/row['download']).read_bytes();self.release('0.6.1')
        self.assertEqual([r['version'] for r in validate(self.root)],['0.6.1','0.6.0'])
        self.assertEqual((self.root/'web'/row['download']).read_bytes(),before)
        page=(self.root/'web/releases.html').read_text();self.assertIn('Download v0.6.1',page);self.assertIn('Download v0.6.0',page)
    def test_core_change_requires_new_version(self):
        self.release();(self.root/'opencaliber/core.py').write_text('value=2\n')
        with self.assertRaisesRegex(ValueError,'Core functionality changed'):validate(self.root)
        self.release('0.6.1');validate(self.root)
    def test_functional_console_changes_are_versioned(self):
        self.release();(self.root/'web/console.js').write_text('changed()')
        with self.assertRaises(ValueError):validate(self.root)
    def test_line_endings_do_not_create_false_changes(self):
        self.release();(self.root/'opencaliber/core.py').write_bytes(b'value=1\r\n');validate(self.root)
    def test_archive_tampering_is_detected(self):
        row=self.release();(self.root/'web'/row['download']).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'archive missing or modified'):validate(self.root)
    def test_missing_notes_and_bad_versions_rejected(self):
        for version in ('../escape','01.2.3','v0.6.0','1.2'):
            with self.assertRaises(ValueError):version_tuple(version)
        with self.assertRaises(ValueError):create('0.6.0','Title',[],root=self.root)

if __name__=='__main__':unittest.main()
