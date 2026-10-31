import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createServer} from 'node:http';
import {Client,normalizeResponse} from '../sdk/typescript/opencaliber.mjs';
const bundle=JSON.parse(await readFile(new URL('../examples/adoption/bundle.json',import.meta.url),'utf8'));
const {policy,agent,task,session_id,workflow_id}=bundle;
const context={policy,agent,task,session_id,workflow_id};

test('unknown mapping is visibly unmapped; raw payload is omitted',()=>{
  const trace=normalizeResponse('anthropic',bundle.responses.anthropic.unsafe,{...context,policy:{version:'none',tools:{}}});
  assert.ok(trace.actions.every(a=>a.tool.startsWith('unmapped.')));
  assert.ok(!JSON.stringify(trace).includes('fixture-secret'));
});
test('reject malformed mappings, partial responses and duplicate IDs',()=>{
  const response=structuredClone(bundle.responses.anthropic.unsafe);
  response.content[1].id=response.content[0].id;
  assert.throws(()=>normalizeResponse('anthropic',response,context));
  assert.throws(()=>normalizeResponse('openai-responses',{status:'in_progress',output:[]},context));
  assert.throws(()=>normalizeResponse('anthropic',bundle.responses.anthropic.unsafe,{...context,policy:{version:'x',tools:{bad:{tool:'arbitrary'}}}}));
});
test('reject remote endpoints and invalid deadlines',()=>{
  assert.throws(()=>new Client({endpoint:'https://outside.test'}));
  assert.throws(()=>new Client({timeoutMs:0}));
  assert.throws(()=>new Client({endpoint:'http://localhost:8787?key=secret'}));
});
test('observer defaults to redacted storage and never dispatches',async()=>{
  let received;
  const server=createServer((req,res)=>{
    let body='';req.on('data',x=>body+=x);req.on('end',()=>{
      received=JSON.parse(body);res.setHeader('Content-Type','application/json');
      res.end(JSON.stringify({id:'local-id',result:{assessment:'review'}}));
    });
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  try {
    const observed=await new Client({endpoint:`http://127.0.0.1:${server.address().port}`}).observeResponse('anthropic',bundle.responses.anthropic.unsafe,context);
    assert.equal(observed.status,'evaluated');assert.equal(observed.execution_decision,'application_owned');
    assert.equal(received.storage,'redacted');assert.ok(!JSON.stringify(received).includes('fixture-secret'));
  } finally {server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
});
test('timeouts and malformed responses do not become clear',async()=>{
  let slow=true;
  const server=createServer((req,res)=>{if(!slow)res.end('{"result":{"assessment":"clear"}}');});
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  try {
    const options={endpoint:`http://127.0.0.1:${server.address().port}`,timeoutMs:40};
    const trace=normalizeResponse('anthropic',bundle.responses.anthropic.unsafe,context);
    const observed=await new Client(options).observe(trace);
    assert.equal(observed.status,'error');assert.equal(observed.assessment,null);
    await assert.rejects(()=>new Client({...options,failureMode:'raise'}).observe(trace));
    slow=false;
    assert.equal((await new Client({...options,timeoutMs:1000}).observe(trace)).status,'error');
  } finally {server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
});
test('redirects are not followed',async()=>{
  const server=createServer((req,res)=>{res.writeHead(307,{Location:'/unexpected'});res.end();});
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  try {
    const client=new Client({endpoint:`http://127.0.0.1:${server.address().port}`});
    assert.equal((await client.observe(normalizeResponse('anthropic',bundle.responses.anthropic.unsafe,context))).status,'error');
  } finally {server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
});


test('projects custom scalar arguments and rejects nested or oversized values',()=>{
  const policy={version:'fields',tools:{read:{tool:'file.read',resource_from:'path',data_class:'public',arguments:{account_id:'payload.account',amount:'amount'}}}};
  const response=value=>({id:'r',output:[{type:'function_call',call_id:'a',name:'read',arguments:JSON.stringify({path:'/workspace/reports/a',payload:{account:value},amount:12.5})}]});
  const trace=normalizeResponse('openai-responses',response('approved'),{...context,policy});
  assert.deepEqual(trace.actions[0].arguments,{account_id:'approved',amount:12.5});
  for(const value of [null,{},[], 'a'.repeat(8001)]) assert.throws(()=>normalizeResponse('openai-responses',response(value),{...context,policy}));
});
