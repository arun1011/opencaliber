"""Real local orchestration with explicit, illustrative failure branches."""
import sys,uuid,os
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from opencaliber.trajectory import Trajectory

def main():
    graph=Trajectory('research-'+uuid.uuid4().hex[:10],endpoint=os.environ.get('OPENCALIBER_ENDPOINT','http://127.0.0.1:8787'),token=os.environ.get('OPENCALIBER_TOKEN'))
    with graph.span('Coordinate research','coordinator',kind='agent') as root:
        with graph.span('Delegate to researcher','coordinator',kind='handoff',parent_id=root['id']) as handoff:
            with graph.span('Research','researcher',kind='agent',parent_id=handoff['id']) as researcher:
                for _ in range(2):
                    with graph.span('Read project README','researcher',parent_id=researcher['id'],work_key='same-readme-v1'):
                        assert Path('README.md').read_text(encoding='utf-8')
                try:
                    with graph.span('Fetch unavailable fixture','researcher',parent_id=researcher['id']) as failed:
                        raise TimeoutError('Deliberate demonstration failure')
                except TimeoutError:pass
                with graph.span('Retry with local evidence','researcher',parent_id=researcher['id'],retry_of=failed['id']):
                    assert Path('README.md').exists()
                with graph.span('Summarize too early','summarizer',kind='agent',parent_id=researcher['id'],depends_on=[failed['id']]) as dependent:
                    dependent['status']='failed';dependent['error_source']=failed['id']
                with graph.span('Delegate back to coordinator','coordinator',kind='agent',parent_id=researcher['id']):pass
                with graph.span('Wait for unreported source','researcher',parent_id=researcher['id'],depends_on=['missing-source']):pass
    if graph.delivery_errors:raise RuntimeError('Graph delivery incomplete; check the console and rerun')
    print('Open console > Execution graphs >',graph.id)
if __name__=='__main__':main()
