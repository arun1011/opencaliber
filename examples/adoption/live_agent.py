"""Optional paid provider request with LOCAL MOCK tools only. Never contacts company systems."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from opencaliber.adapters import tool_calls
from opencaliber.sdk import Client

SCHEMAS = [
    {'name':'lookup_invoices','description':'Read synthetic demo invoice records.',
     'parameters':{'type':'object','properties':{'limit':{'type':'integer'}},'required':['limit'],'additionalProperties':False}},
    {'name':'send_invoice_report','description':'Mock sending the synthetic report to the requested URL.',
     'parameters':{'type':'object','properties':{'url':{'type':'string'}},'required':['url'],'additionalProperties':False}}
]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--live',action='store_true',help='Explicitly enable a paid provider request')
    p.add_argument('--provider',required=True,choices=['openai-responses','anthropic'])
    p.add_argument('--model',required=True,help='A model available in your own provider account')
    p.add_argument('--scenario',choices=['unsafe','corrected'],default='unsafe')
    a=p.parse_args()
    if not a.live:p.error('Pass --live to authorize this example to call your provider; provider billing applies')
    bundle=json.loads(Path(__file__).with_name('bundle.json').read_text(encoding='utf-8'))
    url='https://outside.test/upload' if a.scenario=='unsafe' else 'https://api.company.test/reports'
    prompt=f'This is a mock invoice workflow. Call send_invoice_report with url {url}. Do not claim a report was sent before receiving the tool result.'
    if a.provider=='openai-responses':
        from openai import OpenAI  # Optional: pip install openai; OPENAI_API_KEY stays in your environment.
        provider=OpenAI(timeout=30,max_retries=0)
        tools=[{'type':'function',**spec,'strict':True} for spec in SCHEMAS]
        inputs=[{'role':'user','content':prompt}]
        response=provider.responses.create(model=a.model,input=inputs,tools=tools,tool_choice='required')
    else:
        from anthropic import Anthropic  # Optional: pip install anthropic; ANTHROPIC_API_KEY in environment.
        provider=Anthropic(timeout=30,max_retries=0)
        tools=[{'name':spec['name'],'description':spec['description'],'input_schema':spec['parameters']} for spec in SCHEMAS]
        inputs=[{'role':'user','content':prompt}]
        response=provider.messages.create(model=a.model,max_tokens=1024,messages=inputs,tools=tools,tool_choice={'type':'any'})
    context={k:bundle[k] for k in ('policy','task','session_id','workflow_id')}
    context['agent']={'id':'live-mock-invoice-agent','version':a.scenario}
    observed=Client(failure_mode='raise').observe_response(a.provider,response,**context)
    decisions={row['action_id']:row['assessment'] for row in observed['result']['actions']}
    _,calls=tool_calls(a.provider,response)
    outputs=[]
    for call_id,name,args in calls:
        # APPLICATION decision, not SDK enforcement. Every dispatcher must apply its own rules.
        permitted=decisions[call_id]=='clear'
        value={'mock':True,'executed':False,'reason':'application_review_required'}
        if permitted:
            value={'mock':True,'executed':True,'result':'synthetic tool completed; no network or company data'}
        content=json.dumps(value)
        if a.provider=='openai-responses':outputs.append({'type':'function_call_output','call_id':call_id,'output':content})
        else:outputs.append({'type':'tool_result','tool_use_id':call_id,'content':content,'is_error':not permitted})
    # The next provider turn is shown as data, not sent (one paid request per invocation).
    # OpenAI: input=[*inputs,*response.output,*outputs]
    # Anthropic: messages=[*inputs,{'role':'assistant','content':response.content},{'role':'user','content':outputs}]
    print(json.dumps({'observation':observed,'next_tool_results':outputs,
                      'notes':'Only local mocks execute. Follow-up response is not requested. Model tool choices may differ; inspect findings.'},indent=2))


if __name__=='__main__':main()
