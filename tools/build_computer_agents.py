"""Package bounded browser and document workflows with offline demos."""
import io
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
COMPUTER_AGENTS = json.loads((ROOT/'agent_templates/computer/catalog.json').read_text(encoding='utf-8'))

PACK_TESTS = '''import json, unittest
from pathlib import Path
import agent
class WorkflowTests(unittest.TestCase):
    def test_configuration_and_offline_result(self):
        config=agent.validate(json.loads((agent.ROOT/'config.json').read_text()))
        guard=agent.make_guard(config)
        result=agent.demo(config,guard)
        self.assertTrue(result)
        self.assertTrue(guard.trace['actions'])
        self.assertEqual(agent.evaluate_trace(guard.trace,agent.policy(config))['assessment'],'clear')
    def test_real_path_boundary(self):
        with self.assertRaises(ValueError):agent.inside(agent.ROOT,'../escape')
    def test_exact_host_boundary(self):
        config=json.loads((agent.ROOT/'config.json').read_text())
        config['targets']=[{'url':'https://example.com.attacker.test','must_contain':''}]
        with self.assertRaises(ValueError):agent.validate(config)
    def test_fields_are_drafts(self):
        result=agent.extract_entries('owner: Example User','.txt',['owner','total'])
        self.assertEqual(result,[{'owner':'Example User','total':''}])
if __name__=='__main__':unittest.main()
'''


def build_computer_agent(spec):
    config = {
        'tracking_id':spec['id'],'agent_id':spec['id'],'version':'0.2.0','title':spec['title'],'kind':spec['kind'],
        'allowed_hosts':['example.com'],'allowed_methods':['GET','HEAD'],
        'targets':[{'url':'https://example.com','must_contain':'Example Domain'}],
        'input_dir':'samples','output_dir':'outputs','max_pages':3,'max_files':10,
        'max_input_bytes':500000,'max_text_chars':4000,'timeout_seconds':30,
        'max_download_bytes':5_000_000,'download_extension':'.csv',
        'headless':spec['kind']!='reports','manual_login':spec['kind']=='reports',
        'browser_channel':'',
        'download_selector':'a[data-report-download]','fields':['invoice_id','owner','total'],
        'data_class':spec['data_class']}
    if spec['kind']=='reports':
        config['allowed_methods']=['GET','HEAD','POST']
    pages = [{'url':'https://example.com','title':'Example Domain',
              'excerpt':'SYNTHETIC SAMPLE: the example service supports CSV exports and read-only reports.'}]
    readme = f'''# {spec['title']}

{spec['description']}

This is a bounded, code-driven workflow with a shared runtime and task-specific
configuration. It is not a general desktop controller, autonomous LLM planner or
computer-use model. No model credentials are needed. Inspect `agent.py` and
`config.json` before adapting the workflow. Synthetic demo inputs are included.

## Standard pack structure

- `agent.py`: actual browser/file execution, OpenCaliber pre-dispatch checks and evidence.
- `config.json`: reviewed targets, hosts, limits, selectors, assertions and output paths.
- `policy.json`: engine policy derived from the shipped example configuration.
- `.env.example`: integration notes; this runtime reads no model keys or stored passwords.
- `samples/`: synthetic pages, documents and CSV records.
- `tests/test_agent.py`: offline contract and boundary tests.
- `opencaliber/`: packaged evaluator, field rules, execution wrapper and redaction.
- `requirements.txt`, LICENSE, NOTICE and LICENSING.md.

`policy.json` is a reference snapshot of the shipped defaults. The runner derives
the active policy from config.json and policy(config) in agent.py; edit those
sources when changing controls, rather than editing the snapshot alone.

## Offline demo

Python 3.10+; no dependency installation, account, model or browser needed:

```sh
python agent.py --demo
python -m unittest discover -s tests -v
```

Results are saved in outputs/draft.txt, result.json and evaluation.json. Wrapped actions also register config.json tracking_id and send metadata automatically
to a running console at http://127.0.0.1:8787. Open Monitored agents to inspect
activity and edit the agent policy. For remote machines set OPENCALIBER_ENDPOINT
to your internal HTTPS service and OPENCALIBER_TOKEN privately. New agents start
in report-only mode; enable Enforce in the console and OPENCALIBER_MODE=enforce
for enforcement from the first action. Offline report-only events queue minimized
metadata in outputs/.opencaliber-tracking. Set OPENCALIBER_TRACKING=off for a fully
disconnected demo. Callback contents are not collected automatically. The redacted
saved evidence is not a lossless replay input.

Demo reads
fixtures; it does not claim browser actions ran. Add --overwrite only to replace
reviewed existing outputs. There are no automatic retries.

## Live execution

For the three browser workflows:

```sh
python -m pip install -r requirements.txt
python -m playwright install chromium
# Review config.json before continuing.
python agent.py --run --approve-config
```

The document workflow needs only Python and uses the same live command without
installing Playwright. Place reviewed TXT, Markdown or CSV files in samples.
Extraction reads named CSV columns or `field: value` text lines. Missing fields
remain empty; results are drafts and are never submitted into another system.
To use an existing Chrome or Edge installation, set browser_channel to chrome or
msedge; an empty value uses the Playwright-installed Chromium browser.

### Configure this workflow

- Research: set targets and allowed_hosts. The browser collects titles, source URLs
  and bounded body excerpts, then creates an evidence comparison draft. It does not
  use an LLM to judge claims, generate analysis or verify citations.
- Report collection: replace the example URL with an authorized portal, configure
  its exact report download selector and expected extension (.csv, .pdf or .xlsx).
  Keep headless false; sign in manually in the temporary browser. Approve collection
  at the terminal. Add only required authentication/resource hosts to allowed_hosts.
  GET/HEAD/POST are allowed for manual sign-in; the agent does not fill credentials
  or submit business forms. POST permissions are broad within approved hosts;
  review the portal and chosen download control. No default example download exists.
- UI testing: set targets and must_contain text. It visits pages, checks visible text
  and saves viewport screenshots. Assertion failures return nonzero. Extend the
  reviewed code for additional interactions; arbitrary click scripts are not loaded.
- Documents: set fields and input/output directories inside the extracted pack.
  At most 100 entries are prepared across the bounded file set. No upload occurs.

## Controls and limits

OpenCaliber enforce mode checks declared navigation and file actions before their
callbacks. A browser request handler also checks HTTP(S) destinations/methods;
non-HTTPS and unapproved requests are aborted. Unapproved redirects are checked as
new requests. Service workers are blocked. This is not a network firewall, sandbox,
DNS-pinning mechanism or guarantee of complete browser interception. Restrict the
machine's real network/filesystem access independently for sensitive workloads.

Only the primary tab is processed; no arbitrary autonomous task planning occurs.
Downloads use fixed output names. Extension and save-size checks occur after the
browser has downloaded to temporary storage; they are not streaming transfer limits.
Browser assets, callbacks, temporary files and manual login are not each represented
as canonical agent actions. Network records contain host/allow decisions, not bodies.
The engine does not infer the business effect of a click or scan for secrets/malware.

Manual prompts time out after five minutes. Browser operation timeouts are per step,
not an overall run deadline. A single run is synchronous; do not share its output
folder with concurrent workers. Review before extending it to destructive operations.

Browser contexts are temporary; cookies, credentials and screenshots of the login
page are not intentionally exported. Outputs can still contain sensitive page text,
reports or screenshots and are unencrypted. Do not commit them. Query strings and
fragments are omitted from source URLs; source contents are not automatically redacted.
evaluation.json minimizes trace metadata and records workflow status and the last
pre-dispatch decision. A clear evaluation does not mean a UI assertion passed or
that every underlying operation succeeded. Exceptions retain unknown outcomes.

No credentials are bundled. No emails, payments, account changes or external form
submissions are implemented. Review website terms and obtain access authorization
before live use. Playwright is installed separately under its own license.

References: [downloads](https://playwright.dev/python/docs/downloads),
[network routing](https://playwright.dev/python/docs/network),
[authentication](https://playwright.dev/python/docs/auth).

Original pack software: Apache-2.0. See LICENSE, NOTICE and LICENSING.md.
'''
    # Import through a temporary module is unnecessary: these policies mirror the
    # runtime's declared defaults and are tested against its policy(config).
    from opencaliber.agent_engine import DEFAULT_CONFIG
    import copy
    engine = copy.deepcopy(DEFAULT_CONFIG)
    engine.update(allowed_hosts=config['allowed_hosts'],allowed_file_roots=['/workspace'],max_calls=100,max_records=100,
                  denied_tools=['shell.exec','database.write','database.delete','file.delete','iam.create_key'])
    engine['tool_policies']={'file.read':{'resource':{'path_roots':['/workspace/samples']}},
                             'file.write':{'resource':{'path_roots':['/workspace/outputs']}}}
    files = {name:(ROOT/name).read_text(encoding='utf-8') for name in ('LICENSE','NOTICE','LICENSING.md')}
    for name in ('__init__.py','agent_engine.py','tool_policies.py','execution.py','privacy.py','tracking.py'):
        files['opencaliber/'+name]=(ROOT/'opencaliber'/name).read_text(encoding='utf-8')
    files.update({
        'agent.py':(ROOT/'agent_templates/computer/agent.py').read_text(encoding='utf-8'),
        'README.md':readme,'config.json':json.dumps(config,indent=2),'policy.json':json.dumps(engine,indent=2),
        '.env.example':'# No model key is used. Sign in manually in the live portal browser.\n# Tracking settings are read from .env or environment.\nOPENCALIBER_ENDPOINT=http://127.0.0.1:8787\nOPENCALIBER_TOKEN=\nOPENCALIBER_TRACKING=on\n',
        '.gitignore':'.env\noutputs/\n__pycache__/\n.venv/\nplaywright/.auth/\n',
        'requirements.txt':'# Only live browser workflows need this dependency.\nplaywright>=1.48,<2\n',
        'samples/pages.json':json.dumps(pages,indent=2),
        'samples/invoice.txt':'SYNTHETIC SAMPLE\ninvoice_id: DEMO-001\nowner: Example User\ntotal: 120.50\n',
        'samples/invoices.csv':'invoice_id,owner,total\nDEMO-002,Example Company,79.50\n',
        'tests/test_agent.py':PACK_TESTS})
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
        for name, text in files.items():archive.writestr(spec['id']+'/'+name,text)
    return stream.getvalue()
