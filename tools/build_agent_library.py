"""Build first-party starter ZIPs using an exact file allowlist; no credentials or outputs."""
import io
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]
AGENTS=[
    {'id':'document-summarizer','title':'Document Summarizer','kind':'documents',
     'description':'Read text or Markdown files from a configured folder and save a draft summary.',
     'instructions':'Summarize the supplied documents. List key points and unresolved questions. Cite the supplied filenames. Do not invent facts.',
     'sample_name':'project-notes.md','sample':'# Synthetic project notes\nThe team will release an invoice reporting prototype.\nThe first milestone is a CSV report and a read-only review.\nOpen question: which date should the prototype ship?\n',
     'tags':['Documents','Summaries','Read and draft'],'data_class':'internal'},
    {'id':'invoice-report-assistant','title':'Invoice Report Assistant','kind':'invoices',
     'description':'Read invoice CSV files and write a report for review. No payments or report delivery.',
     'instructions':'Prepare a draft invoice report from the supplied CSV. Report invoice count, totals and missing fields. Treat calculations as provisional and show the source rows. Do not initiate payments or send reports.',
     'sample_name':'invoices.csv','sample':'invoice_id,customer,amount\nDEMO-001,Example Company A,120.50\nDEMO-002,Example Company B,79.50\n',
     'tags':['Invoices','CSV','Draft reports'],'data_class':'pii'},
    {'id':'support-reply-drafter','title':'Support Reply Drafter','kind':'support',
     'description':'Turn supplied support tickets into draft replies. Review and send them in your own system.',
     'instructions':'Draft a support reply for the supplied ticket. Acknowledge the issue and ask for missing information. Do not promise refunds, account changes, delivery dates or completed actions. Do not send any message.',
     'sample_name':'ticket.txt','sample':'SYNTHETIC TICKET\nCustomer: Example User\nIssue: The invoice export button shows an error.\nMissing: browser version and the exact error text.\n',
     'tags':['Support','Draft replies','Tickets'],'data_class':'pii'}
]

for entry,industry,function in zip(AGENTS,['Cross-industry','Cross-industry','Cross-industry'],['Operations','Finance Operations','Customer Support']):
    entry.update(industry=industry,function=function,output_sections=['Draft','Source references','Missing information'])
AGENTS += json.loads((ROOT/'agent_templates/catalog.json').read_text(encoding='utf-8'))
assert len({entry['id'] for entry in AGENTS})==len(AGENTS)

TESTS='''import json,unittest
import agent
class AgentTests(unittest.TestCase):
    def test_demo_and_evaluation(self):
        cfg=json.loads((agent.ROOT/'config.json').read_text())
        inputs=agent.read_inputs(cfg)
        self.assertTrue(agent.demo_draft(cfg,inputs).startswith('DEMO'))
        result=agent.evaluate(cfg,inputs,False)
        self.assertEqual(result['assessment'],'clear')
        self.assertEqual(result['agent']['id'],cfg['agent_id'])
    def test_live_trace_targets_selected_provider(self):
        cfg=json.loads((agent.ROOT/'config.json').read_text())
        cfg['provider']='anthropic'
        result=agent.evaluate(cfg,agent.read_inputs(cfg),True)
        self.assertEqual(result['assessment'],'clear')
        self.assertTrue(any(a['resource']=='https://api.anthropic.com' for a in result['actions']))
if __name__=='__main__':unittest.main()
'''


def build_agent(spec):
    config={'agent_id':spec['id'],'version':'0.1.0','title':spec['title'],'kind':spec['kind'],
            'provider':'openai','input_dir':'samples','output_dir':'outputs','max_files':25,
            'max_input_bytes':500000,'max_output_tokens':1500,'timeout_seconds':30,
            'data_class':spec['data_class'],'instructions':spec['instructions'],'industry':spec['industry'],'function':spec['function'],'output_sections':spec['output_sections']}
    readme=f'''# {spec['title']} — v0.1.0

{spec['description']}

Industry: {spec['industry']} · Function: {spec['function']}

Requested output sections: {', '.join(spec['output_sections'])}. This starter uses the shared bounded drafting runtime with task-specific instructions and synthetic inputs.

Python 3.10+; standard library only. This is a bounded, first-party draft workflow, not an autonomous agent framework. Source and sample data are included. Samples are synthetic.

## Try without credentials

Extract the ZIP, open a terminal in this folder, then run:

```sh
python agent.py --demo
```

The demo is deterministic and labeled DEMO; it is not a model-generated result. Inspect outputs/draft.txt and outputs/evaluation.json. Existing outputs are protected; add --overwrite only when you intend to replace them.

## Use a provider

Copy .env.example to .env (Windows: `copy .env.example .env`; macOS/Linux: `cp .env.example .env`).
Set OPENAI_API_KEY and OPENAI_MODEL for a model available in your OpenAI account. For Anthropic, set provider to anthropic in config.json and supply ANTHROPIC_API_KEY and ANTHROPIC_MODEL. Never commit or share .env. Existing environment variables take precedence.

```sh
python agent.py --run
# Add --overwrite if demo outputs already exist.
```

Live mode sends the selected input contents to the configured provider and incurs provider charges. No fixed monetary limit is enforced; max_input_bytes and max_output_tokens bound request size, not cost. Provider requests have no automatic retries. Model output is a draft that may be inaccurate; review before use. The examples support one text generation request, not provider tool-call loops.

## Configuration and permissions

Edit config.json: choose provider, input_dir, output_dir, data_class, instructions, max_files, max_input_bytes, max_output_tokens and timeout_seconds. Input files can be .txt, .md, .csv or .json in the configured directory (not recursive). Keep sensitivity labels accurate. Output must stay inside the extracted project. Inputs that escape the selected folder through links are rejected. File reads and draft writes are the only filesystem operations; no email, payment or generated-code execution is provided.

OpenCaliber evaluates the workflow's declared operations and records agent/version attribution, findings and configuration fingerprint in evaluation.json. Logical /workspace paths refer to the configured inputs and outputs; the application itself checks real filesystem paths. Evaluation does not inspect model intent or guarantee prompt-injection protection. Changing configuration changes what the application permits. The pack includes the engine but not the console; import its JSON result or use the separate OpenCaliber console integration if you need saved dashboard history.

## Tests and limits

```sh
python -m unittest discover -s tests -v
```

Included tests cover the sample draft, agent attribution and provider destination in the declared workflow. They do not certify security or provider output quality. Live provider calls have not been exercised as part of this release. Provider formats follow https://developers.openai.com/api/docs/guides/text and https://platform.claude.com/docs/en/api/messages .

Credentials stay in .env or environment variables and are sent only in request headers to the chosen provider. The app makes no telemetry calls. Input contents and generated drafts may contain sensitive data; files are unencrypted. Evaluation results contain resource filenames but no source contents or credentials. Protect outputs and review provider data policies before live use.

License: Apache-2.0. See LICENSE, NOTICE and LICENSING.md.
'''
    files={'LICENSE':(ROOT/'LICENSE').read_text(encoding='utf-8'),
           'NOTICE':(ROOT/'NOTICE').read_text(encoding='utf-8'),
           'LICENSING.md':(ROOT/'LICENSING.md').read_text(encoding='utf-8'),
           'agent.py':(ROOT/'agent_templates/agent.py').read_text(encoding='utf-8'),
           'config.json':json.dumps(config,indent=2),'README.md':readme,
           '.env.example':'# Select a provider in config.json and supply its key and model.\nOPENAI_API_KEY=\nOPENAI_MODEL=\nANTHROPIC_API_KEY=\nANTHROPIC_MODEL=\n',
           '.gitignore':'.env\noutputs/\n__pycache__/\n.venv/\n',
           'requirements.txt':'# Python 3.10+ standard library only; no packages to install.\n',
           'samples/'+spec['sample_name']:spec['sample'],'tests/test_agent.py':TESTS,
           'opencaliber/__init__.py':(ROOT/'opencaliber/__init__.py').read_text(encoding='utf-8'),
           'opencaliber/tool_policies.py':(ROOT/'opencaliber/tool_policies.py').read_text(encoding='utf-8'),
           'opencaliber/agent_engine.py':(ROOT/'opencaliber/agent_engine.py').read_text(encoding='utf-8')}
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,text in files.items():archive.writestr(spec['id']+'/'+name,text)
    return stream.getvalue()


def main():
    destination=ROOT/'web/downloads/agents';destination.mkdir(parents=True,exist_ok=True)
    catalog=[]
    for spec in AGENTS:
        raw=build_agent(spec);(destination/(spec['id']+'.zip')).write_bytes(raw)
        catalog.append({k:spec[k] for k in ('id','title','description','tags','industry','function','output_sections')} | {
            'version':'0.1.0','providers':['OpenAI','Anthropic'],'download':'downloads/agents/'+spec['id']+'.zip',
            'size_bytes':len(raw),'requirements':'Python 3.10+','mode':'Draft workflow','credentials':'Not needed for demo; provider key and model for live use'})
    (ROOT/'web/agents.json').write_text(json.dumps(catalog,indent=2),encoding='utf-8')
    print('Built',len(catalog),'agent packs')


if __name__=='__main__':main()
