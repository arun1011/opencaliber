import copy,tempfile,json,unittest
from pathlib import Path
from unittest.mock import patch
from opencaliber.download_ledger import empty,merge
from opencaliber.download_stats import summarize,snapshot_report,report,_CACHE
from tools.release_downloads import ready_tag

REPO='arun1011/opencaliber';CAT=[{'id':'agent-one','title':'Agent One'}]
def release(count=5,ident=1,tag='v1.0.0'):
 return {'tag_name':tag,'draft':False,'assets':[{'id':ident,'name':'opencaliber.zip','download_count':count,'state':'uploaded','size':100},{'id':ident+100,'name':'agent-one.zip','download_count':2,'state':'uploaded','size':100},{'id':ident+200,'name':'SHA256SUMS.txt','download_count':20,'state':'uploaded','size':100}]}
class DownloadTests(unittest.TestCase):
 def test_totals_ignore_checksum_and_unknown_assets(self):
  r=summarize([release()],REPO,CAT);self.assertEqual(r['total_downloads'],7);self.assertEqual(r['console_downloads'],5)
 def test_snapshot_never_reduces_or_removes_counts(self):
  prior=merge(empty(REPO),[release()],REPO,CAT,now='2026-11-01T10:00:00Z')
  result=merge(prior,[release(1)],REPO,CAT,now='2026-11-01T11:00:00Z');self.assertEqual(result['total_downloads'],7)
  missing=merge(result,[],REPO,CAT,now='2026-11-02T11:00:00Z');self.assertEqual(missing['total_downloads'],7);self.assertEqual(len(missing['daily_totals']),2)
  self.assertEqual(prior['total_downloads'],7);self.assertIsNone(prior['legacy_pages_downloads'])
 def test_new_asset_id_adds_without_erasing_old(self):
  a=merge(empty(REPO),[release()],REPO,CAT,now='2026-11-01T10:00:00Z')
  b=merge(a,[release(3,2,'v2.0.0')],REPO,CAT,now='2026-11-02T10:00:00Z');self.assertEqual(b['total_downloads'],12)
  self.assertEqual(snapshot_report(b,REPO)['total_downloads'],12)
 def test_corrupt_prior_does_not_reset(self):
  a=empty(REPO);a['total_downloads']=999
  with self.assertRaises(ValueError):merge(a,[],REPO,CAT)
  a=empty(REPO);a['repository']='other/repo'
  with self.assertRaises(ValueError):merge(a,[],REPO,CAT)
 def test_unchanged_counts_same_day_do_not_change_file(self):
  a=merge(empty(REPO),[release()],REPO,CAT,now='2026-11-01T10:00:00Z')
  self.assertEqual(a,merge(a,[release()],REPO,CAT,now='2026-11-01T11:00:00Z'))
 def test_release_links_require_complete_stable_release(self):
  r=release();self.assertEqual(ready_tag(r,CAT),'v1.0.0');r['assets'].pop();self.assertEqual(ready_tag(r,CAT),'')
  r=release();r['prerelease']=True;self.assertEqual(ready_tag(r,CAT),'')
 def test_report_reads_persisted_file_and_caches(self):
  a=merge(empty(REPO),[release()],REPO,CAT);_CACHE.clear()
  with patch('opencaliber.download_stats.read_snapshot',return_value=a) as read:
   self.assertTrue(report(CAT)['persisted']);report(CAT);self.assertEqual(read.call_count,1)
  _CACHE.clear()
 def test_no_release_is_setup_required_not_fake_zero(self):
  r=summarize([],REPO,CAT);self.assertEqual(r['status'],'setup_required');self.assertIsNone(r['total_downloads'])
if __name__=='__main__':unittest.main()
