"""Persist minimized comparison reports, never submitted raw traces or inputs."""
import json,secrets,re
from .comparison import compare

def initialize(conn):conn.execute('CREATE TABLE IF NOT EXISTS comparisons (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, report TEXT NOT NULL)')

def save(bundle,connect,timestamp):
    report=compare(bundle);ident=secrets.token_hex(8);created=timestamp()
    with connect() as c:c.execute('INSERT INTO comparisons VALUES(?,?,?)',(ident,created,json.dumps(report,allow_nan=False)))
    return {'id':ident,'created_at':created,'report':report}

def list_reports(connect):
    with connect() as c:rows=c.execute('SELECT * FROM comparisons ORDER BY created_at DESC LIMIT 30').fetchall()
    return [{'id':r['id'],'created_at':r['created_at'],**{k:json.loads(r['report'])[k] for k in ('agent_id','baseline_version','candidate_version','baseline','candidate')}} for r in rows]

def get_report(ident,connect):
    if not isinstance(ident,str) or not re.fullmatch('[0-9a-f]{16}',ident):raise ValueError('Invalid comparison ID')
    with connect() as c:row=c.execute('SELECT * FROM comparisons WHERE id=?',(ident,)).fetchone()
    return {'id':row['id'],'created_at':row['created_at'],'report':json.loads(row['report'])} if row else None
