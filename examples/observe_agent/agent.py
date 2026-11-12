"""An ordinary agent workload: no OpenCaliber imports or wrappers."""
import sqlite3
from contextlib import closing

with closing(sqlite3.connect(':memory:')) as db:
    db.execute('CREATE TABLE tickets(id INTEGER, topic TEXT)')
    db.execute('INSERT INTO tickets VALUES (?, ?)', (1, 'billing'))
    rows = db.execute('SELECT id FROM tickets WHERE topic=?', ('billing',)).fetchall()
    print('Matching tickets:', len(rows))
