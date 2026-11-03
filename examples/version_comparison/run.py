"""Run the illustrative paired agents and export a bundle plus a review report."""
from pathlib import Path
import json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from opencaliber.comparison_demo import demo_bundle
from opencaliber.comparison import compare
if __name__=='__main__':
    out=Path(sys.argv[1]) if len(sys.argv)>1 else Path('outputs/version-comparison')
    out.mkdir(parents=True,exist_ok=True)
    bundle=demo_bundle();report=compare(bundle)
    (out/'comparison-input.json').write_text(json.dumps(bundle,indent=2),encoding='utf-8')
    (out/'comparison-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('Import into Compare agent versions:',out/'comparison-input.json')
    print('Task successes:',report['baseline']['task_successes'],'->',report['candidate']['task_successes'])
    print('Review-only proposals:',len(report['proposals']))
