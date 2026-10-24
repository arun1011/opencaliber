// node examples/adoption/provider_demo.mjs [provider]
// Starts no provider requests and dispatches no tools; requires the local console server.
import {readFile} from 'node:fs/promises';
import {Client} from '../../sdk/typescript/opencaliber.mjs';
const bundle=JSON.parse(await readFile(new URL('./bundle.json',import.meta.url),'utf8'));
const provider=process.argv[2]??'openai-responses';
if(!['openai-responses','openai-chat','anthropic'].includes(provider)) throw Error('Unsupported provider');
const {policy,task,agent,session_id,workflow_id}=bundle;
const client=new Client({failureMode:'raise'});
for(const scenario of ['unsafe','corrected']) {
  const observed=await client.observeResponse(provider,bundle.responses[provider][scenario],{
    policy,task,agent:{...agent,version:scenario==='unsafe'?'demo-v1':'demo-v2'},session_id,workflow_id
  });
  if(observed.status!=='evaluated'||observed.result.assessment!==(scenario==='unsafe'?'violation':'clear')) throw Error('Demo expectation failed');
  console.log(JSON.stringify({source:'recorded synthetic fixture',provider,scenario,...observed},null,2));
}
