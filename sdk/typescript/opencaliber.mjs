// Node 18+; typed by opencaliber.d.mts. No provider SDK dependency.
import { createHash } from 'node:crypto';
const own = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
const object = x => x !== null && typeof x === 'object' && !Array.isArray(x);
const known = new Set(['database.backup','file.backup','database.read','database.write','database.delete','file.read','file.write','file.delete','http.get','http.send','email.send','shell.exec','iam.create_key','payments.refund','calendar.read','calendar.write','search.query']);
const canonical = x => Array.isArray(x) ? `[${x.map(canonical).join(',')}]` : object(x) ? `{${Object.keys(x).sort().map(k=>`${JSON.stringify(k)}:${canonical(x[k])}`).join(',')}}` : JSON.stringify(x);
const text = (x, n=300) => typeof x === 'string' && x.trim().length > 0 && x.length <= n;
const select = (args, path) => {
  let value=args;
  for(const part of path.split('.')) {
    if(!object(value)||!own(value,part)) throw Error('Required mapped argument is missing');
    value=value[part];
  }
  return value;
};
export function normalizeResponse(provider, response, context) {
  const {policy, agent, task, session_id, workflow_id} = context;
  if(!object(response)||!object(policy)||Object.keys(policy).sort().join(',')!=='tools,version'||!text(policy.version,120)||!object(policy.tools)||Object.keys(policy.tools).length>100) throw Error('Invalid policy or response');
  if(!object(agent)||Object.keys(agent).sort().join(',')!=='id,version'||!text(agent.id,120)||!text(agent.version,120)||!text(session_id)||!object(task)||!text(task.goal,4000)) throw Error('Agent, session and task are required');
  if(workflow_id!==undefined&&!text(workflow_id,120)) throw Error('Invalid workflow ID');
  for(const [name,spec] of Object.entries(policy.tools)) {
    if(!text(name)||!object(spec)||Object.keys(spec).some(k=>!['tool','resource','resource_from','arguments','data_class'].includes(k))||!known.has(spec.tool)||own(spec,'resource')===own(spec,'resource_from')||!text(spec.resource??spec.resource_from,1000)||!['public','internal','pii','secret'].includes(spec.data_class)) throw Error('Invalid tool mapping');
    if(spec.arguments!==undefined&&(!object(spec.arguments)||Object.keys(spec.arguments).length>50||Object.entries(spec.arguments).some(([k,v])=>!/^[A-Za-z_][A-Za-z0-9_]{0,79}$/.test(k)||!text(v)))) throw Error('Invalid argument mapping');
  }
  let calls=[];
  if(provider==='openai-responses') {
    if(response.status!==undefined&&response.status!=='completed'||!Array.isArray(response.output)) throw Error('Use completed Responses output');
    for(const block of response.output) {
      if(block.type==='function_call') {
        if(block.status!==undefined&&block.status!=='completed') throw Error('Incomplete call');
        calls.push([block.call_id,block.name,block.arguments]);
      } else if(!['message','reasoning'].includes(block.type)) throw Error('Unsupported output type');
    }
  } else if(provider==='openai-chat') {
    if(!Array.isArray(response.choices)||response.choices.length!==1||response.choices[0].finish_reason!=='tool_calls') throw Error('Use one completed tool_calls choice');
    const blocks=response.choices[0].message?.tool_calls;
    if(!Array.isArray(blocks)) throw Error('Missing tool calls');
    for(const block of blocks) {
      if(block.type!=='function') throw Error('Unsupported call type');
      calls.push([block.id,block.function?.name,block.function?.arguments]);
    }
  } else if(provider==='anthropic') {
    if(response.stop_reason!=='tool_use'||!Array.isArray(response.content)) throw Error('Use completed tool_use content');
    for(const block of response.content) {
      if(block.type==='tool_use') {
        if(block.toolset_name) throw Error('Toolsets unsupported');
        calls.push([block.id,block.name,block.input]);
      } else if(!['text','thinking','redacted_thinking'].includes(block.type)) throw Error('Unsupported content type');
    }
  } else throw Error('Unsupported provider');
  if(!calls.length||calls.length>200) throw Error('Expected 1–200 completed tool calls');
  const ids=new Set();
  const actions=calls.map(([id,name,input])=>{
    if(!text(id,1000)||!text(name,300)||ids.has(id)) throw Error('Invalid or duplicate call identity');
    ids.add(id);
    const args=typeof input==='string'?JSON.parse(input):input;
    if(!object(args)) throw Error('Arguments must be an object');
    const spec=own(policy.tools,name)?policy.tools[name]:undefined;
    if(!spec) return {id,source_tool:name,tool:'unmapped.'+name,resource:'[unmapped]'};
    const resource=own(spec,'resource')?spec.resource:select(args,spec.resource_from);
    if(!text(resource,1000)) throw Error('Invalid mapped resource');
    const projected=Object.fromEntries(Object.entries(spec.arguments??{}).map(([key,path])=>[key,select(args,path)]));
    if(Object.values(projected).some(v=>!(typeof v==='boolean'||typeof v==='string'&&v.length<=8000||typeof v==='number'&&Number.isFinite(v)&&Math.abs(v)<=1e12))) throw Error('Arguments require bounded non-null scalar values');
    if(projected.records!==undefined&&(!Number.isSafeInteger(projected.records)||projected.records<0||projected.records>1e12)) throw Error('Invalid records');
    for(const key of ['command','destination']) if(projected[key]!==undefined&&(typeof projected[key]!=='string'||projected[key].length>8000)) throw Error('Invalid mapped argument');
    return {id,source_tool:name,tool:spec.tool,resource,arguments:projected,data_class:spec.data_class};
  });
  const trace={name:provider+' tool calls',agent:structuredClone(agent),task:structuredClone(task),actions,
    context:{provider,response_id:response.id??'not-supplied',session_id,policy_version:policy.version,policy_sha256:createHash('sha256').update(canonical(policy)).digest('hex')}};
  if(workflow_id!==undefined) trace.workflow_id=workflow_id;
  return trace;
}
export class Client {
  constructor({endpoint='http://127.0.0.1:8787',timeoutMs=2000,failureMode='return_error'}={}) {
    const url=new URL(endpoint);
    if(url.protocol!=='http:'||!['127.0.0.1','localhost'].includes(url.hostname)||url.username||url.password||url.pathname!=='/'||url.search||url.hash) throw Error('Use the local loopback endpoint');
    if(!Number.isFinite(timeoutMs)||timeoutMs<=0||timeoutMs>30000||!['return_error','raise'].includes(failureMode)) throw Error('Invalid client options');
    this.endpoint=url.origin;this.timeoutMs=timeoutMs;this.failureMode=failureMode;
  }
  async observe(trace,{storage='redacted'}={}) {
    if(!['redacted','raw'].includes(storage)) throw Error('Invalid storage');
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),this.timeoutMs),start=Date.now();
    try {
      const response=await fetch(this.endpoint+'/api/evaluate',{method:'POST',redirect:'error',signal:controller.signal,headers:{'Content-Type':'application/json'},body:JSON.stringify({trace,storage})});
      if(!response.ok) throw Error('Evaluation failed');
      const data=await response.json();
      if(!text(data.id)||!object(data.result)||!['clear','review','violation'].includes(data.result.assessment)) throw Error('Invalid evaluator response');
      return {...data,status:'evaluated',mode:'observe',execution_decision:'application_owned',elapsed_ms:Date.now()-start};
    } catch {
      if(this.failureMode==='raise') throw Error('Local evaluation unavailable; no execution decision made');
      return {status:'error',mode:'observe',assessment:null,execution_decision:'application_owned',error:'evaluation_unavailable'};
    } finally {clearTimeout(timer);}
  }
  async observeResponse(provider,response,context,options={}) {
    return this.observe(normalizeResponse(provider,response,context),options);
  }
}
