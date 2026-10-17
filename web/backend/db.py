"""SQLite CRUD for the single-user LOCAL hackathon demonstrator."""
import sqlite3,json,datetime
from pathlib import Path
DB=Path(__file__).resolve().parents[1]/'runtime'/'agrovision.sqlite3'
TABLES={'plants':('culture','variety','location','bed','planted_at','description'),
'observations':('plant_id','date','category','description','action','outcome','photo_url','analysis_id'),
'lots':('title','culture','quantity','unit','price','currency','status','buyer','description','photo_url'),
'recommendations':('title','evidence','explanation','action','certainty','verify','status','outcome','plant_id')}
def conn():
 DB.parent.mkdir(exist_ok=True,parents=True)
 c=sqlite3.connect(DB);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON');return c

def init():
 with conn() as c:
  for name,cols in TABLES.items():
   defs=','.join(f'{col} '+('REAL' if col in ('quantity','price') else 'TEXT') for col in cols)
   c.execute(f'CREATE TABLE IF NOT EXISTS {name} (id INTEGER PRIMARY KEY AUTOINCREMENT, {defs},created_at TEXT NOT NULL, updated_at TEXT NOT NULL)')
  c.execute('CREATE TABLE IF NOT EXISTS analyses (id TEXT PRIMARY KEY, original_url TEXT NOT NULL, overlay_url TEXT NOT NULL, result_json TEXT NOT NULL, created_at TEXT NOT NULL)')

def all_rows(name):
 with conn() as c:
  return [dict(x) for x in c.execute(f'SELECT * FROM {name} ORDER BY id DESC').fetchall()]
def one(name,id):
 with conn() as c:
  row=c.execute(f'SELECT * FROM {name} WHERE id=?',(id,)).fetchone();return dict(row) if row else None

def save(name,data,id=None):
 cols=TABLES[name];payload={k:data.get(k) for k in cols if k in data}
 now=datetime.datetime.now(datetime.timezone.utc).isoformat()
 with conn() as c:
  if id:
   if not one(name,id):return None
   payload['updated_at']=now
   if payload:c.execute(f"UPDATE {name} SET "+','.join(f'{k}=?' for k in payload)+" WHERE id=?",(*payload.values(),id))
   c.commit()
   return one(name,id)
  payload['created_at']=now;payload['updated_at']=now
  cur=c.execute(f'INSERT INTO {name} ('+','.join(payload)+') VALUES ('+','.join('?' for _ in payload)+')',tuple(payload.values()))
  c.commit()
  return one(name,cur.lastrowid)
def delete(name,id):
 with conn() as c:
  cur=c.execute(f'DELETE FROM {name} WHERE id=?',(id,));return cur.rowcount>0

def add_analysis(id,original,overlay,result):
 with conn() as c:c.execute('INSERT INTO analyses VALUES (?,?,?,?,?)',(id,original,overlay,json.dumps(result,ensure_ascii=False),datetime.datetime.now(datetime.timezone.utc).isoformat()))
def get_analysis(id):
 with conn() as c:
  row=c.execute('SELECT * FROM analyses WHERE id=?',(id,)).fetchone()
  if row:
   d=dict(row);d['result']=json.loads(d.pop('result_json'));return d
  return None
def update_analysis(id,result,overlay_url):
 with conn() as c:c.execute('UPDATE analyses SET result_json=?,overlay_url=? WHERE id=?',(json.dumps(result,ensure_ascii=False),overlay_url,id))


def list_analyses():
 with conn() as c:
  rows=c.execute('SELECT * FROM analyses ORDER BY created_at DESC LIMIT 200').fetchall()
  return [{'id':d['id'],'original_url':d['original_url'],'overlay_url':d['overlay_url'],'created_at':d['created_at'],**json.loads(d['result_json'])} for d in rows]
