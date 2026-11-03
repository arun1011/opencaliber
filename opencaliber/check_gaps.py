"""Actionable gaps. Enabled code never fabricates absent evidence or coverage."""
from .custom_checks import listing,expression

def enrich(agent,latest,connect):
    active=[c for c in listing(connect) if c['enabled'] and (not c['spec']['tracking_ids'] or agent['tracking_id'] in c['spec']['tracking_ids'])]
    results=(latest or {}).get('custom_checks',[])
    confirmed=[c for c in active if any(r['id']==c['spec']['id'] and r['revision']==c['revision'] and r['status'] in ('passed','failed') for r in results)]
    gaps=[]
    for gap in agent['gaps']:
        marker=': No explicit argument constraints for: '
        if marker in gap:
            tool,tail=gap.split(marker,1);fields=tail.split('. Review',1)[0].split(', ')
            covered={p.removeprefix('action.arguments.') for c in confirmed if c['spec']['tool']==tool for p in expression(c['spec']['code'])[1] if p.startswith('action.arguments.')}
            fields=[f for f in fields if f not in covered]
            if not fields:continue
            gap=tool+marker+', '.join(fields)+'. Review whether these fields need limits or allowlists.'
        gaps.append(gap)
    for c in active:
        matching=[r for r in results if r['id']==c['spec']['id'] and r['revision']==c['revision']]
        if not matching:gaps.append('Custom check '+c['spec']['name']+' is enabled; run its scoped tool again to verify evidence.')
        for r in matching:
            if r['status'] in ('unknown','pending'):gaps.append('Custom check '+c['spec']['name']+': '+r['reason'])
    agent['gaps']=gaps
    agent['custom_capabilities']=[{'id':c['spec']['id'],'name':c['spec']['name'],'tool':c['spec']['tool'],'revision':c['revision'],'evidence_verified':c in confirmed} for c in active]
    agent['gap_actions']=[]
    for gap in gaps:
        tool=next((t['tool'] for t in agent.get('readiness',{}).get('tools',[]) if gap.startswith(t['tool']+':')),None)
        kind='check' if 'No explicit argument constraints' in gap or 'No canonical tool semantics' in gap else 'policy' if 'prerequisite configured' in gap or 'override' in gap else 'contract' if 'contract case' in gap else 'evidence'
        agent['gap_actions'].append({'message':gap,'kind':kind,'tool':tool,'tracking_id':agent['tracking_id']})
