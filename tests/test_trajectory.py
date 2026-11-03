import copy
import sqlite3
import unittest
from contextlib import contextmanager
from opencaliber.trajectory import Trajectory,analyze,save,report,checked

class TrajectoryTests(unittest.TestCase):
    def graph(self):return Trajectory('test',sender=lambda body:None)
    def test_normal_parent_and_retry(self):
        g=self.graph()
        with g.span('job','a',kind='agent') as root:
            with g.span('read','b',parent_id=root['id'],work_key='x') as first:pass
            with g.span('read','b',parent_id=root['id'],retry_of=first['id'],work_key='x'):pass
        r=analyze(g.id,list(g.spans.values()));self.assertEqual(r['findings'],[]);self.assertEqual(len(r['edges']),3)
    def test_duplicate_review(self):
        g=self.graph()
        for _ in range(2):
            with g.span('read','a',work_key='same'):pass
        self.assertIn('POSSIBLE_REDUNDANT_WORK',str(analyze(g.id,list(g.spans.values()))))
    def test_delegation_cycle(self):
        g=self.graph()
        with g.span('root','a',kind='agent') as a:
            with g.span('child','b',kind='agent',parent_id=a['id']) as b:
                with g.span('return','a',kind='agent',parent_id=b['id']):pass
        self.assertIn('CIRCULAR_DELEGATION',str(analyze(g.id,list(g.spans.values()))))
    def test_dependency_at_dispatch_and_error(self):
        g=self.graph()
        with g.span('source','a') as a:a['status']='failed'
        with g.span('consumer','b',depends_on=[a['id'],'missing']) as b:
            b['status']='failed';b['error_source']=a['id']
        r=str(analyze(g.id,list(g.spans.values())))
        for code in ('DEPENDENCY_NOT_READY','MISSING_EVIDENCE','ERROR_PROPAGATION'):self.assertIn(code,r)
    def test_late_evidence_resolves_missing(self):
        g=self.graph()
        with g.span('first','a') as a:pass
        with g.span('second','b',depends_on=[a['id']]):pass
        self.assertNotIn('MISSING_EVIDENCE',str(analyze(g.id,list(g.spans.values()))))
    def test_store_duplicates_and_immutable_terminal(self):
        db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
        @contextmanager
        def connect():
            with db:yield db
        captured=[];g=Trajectory('test',sender=lambda body:captured.append(copy.deepcopy(body)))
        with g.span('read','a'):pass
        self.assertEqual(save(captured[0],connect,lambda:'now')['status'],'accepted')
        self.assertEqual(save(captured[0],connect,lambda:'now')['status'],'duplicate')
        save(captured[1],connect,lambda:'now')
        changed=copy.deepcopy(captured[1]);changed['span']['sequence']=3
        with self.assertRaises(ValueError):save(changed,connect,lambda:'now')
        self.assertEqual(report('test',connect)['nodes'][0]['status'],'succeeded');db.close()
    def test_exception_recorded_and_propagated(self):
        g=self.graph()
        with self.assertRaises(TimeoutError):
            with g.span('request','a'):raise TimeoutError()
        self.assertEqual(next(iter(g.spans.values()))['status'],'failed')
    def test_reject_extra_payload(self):
        g=self.graph()
        with g.span('read','a') as s:pass
        s['secret']='not allowed'
        with self.assertRaises(ValueError):checked({'trajectory_id':'test','span':s})
    def test_dependency_cycle(self):
        g=self.graph()
        with g.span('a','a') as a:pass
        with g.span('b','b',depends_on=[a['id']]) as b:pass
        a['depends_on']=[b['id']];a['dependency_status']={b['id']:'unknown'}
        self.assertIn('DEPENDENCY_CYCLE',str(analyze(g.id,list(g.spans.values()))))

if __name__=='__main__':unittest.main()
