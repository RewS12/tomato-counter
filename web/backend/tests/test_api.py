import json
from pathlib import Path
import numpy as np
import cv2
import pytest
from fastapi.testclient import TestClient
from backend import db
from backend.main import app

@pytest.fixture()
def client(tmp_path,monkeypatch):
 monkeypatch.setattr(db,'DB',tmp_path/'db.sqlite3')
 db.init()
 return TestClient(app)

def photo():
 img=np.full((500,760,3),(235,235,235),np.uint8)
 cv2.circle(img,(180,200),54,(30,30,220),-1)
 cv2.circle(img,(410,260),54,(60,160,130),-1)
 ok,buf=cv2.imencode('.png',img)
 return buf.tobytes()

def test_start_routes(client):
 for route in ['/','/app','/apiv2/health','/apiv2/demo','/apiv2/evaluation','/apiv2/knowledge','/apiv2/plants','/sw.js']:
  assert client.get(route).status_code==200

def test_analyze_real_pixels_and_revision(client):
 a=client.post('/apiv2/analyze/fruits',files={'file':('test.png',photo(),'image/png')})
 assert a.status_code==200,a.text
 data=a.json();assert data['total']>=1;assert data['ripe']>=1
 saved=client.get('/apiv2/analyses/'+data['id']);assert saved.status_code==200
 changed=client.put('/apiv2/analyses/'+data['id']+'/objects',json={'data':{'objects':[]}})
 assert changed.status_code==200;assert changed.json()['total']==0
 assert client.get('/apiv2/analyses/'+data['id']).json()['total']==0

def test_different_photos_produce_different_counts(client):
 zero=cv2.imencode('.png',np.full((500,760,3),220,np.uint8))[1].tobytes()
 a=client.post('/apiv2/analyze/fruits',files={'file':('a.png',photo(),'image/png')}).json()['total']
 b=client.post('/apiv2/analyze/fruits',files={'file':('b.png',zero,'image/png')}).json()['total']
 assert a>b and b==0

def test_bad_file(client):
 assert client.post('/apiv2/analyze/fruits',files={'file':('wrong.txt',b'abc','text/plain')}).status_code==415
 assert client.post('/apiv2/analyze/fruits',files={'file':('wrong.jpg',b'abc','image/jpeg')}).status_code==422

def test_crud_persistence(client):
 p=client.post('/apiv2/plants',json={'data':{'culture':'Томаты','variety':'Черри','bed':'2'}})
 assert p.status_code==201;pid=p.json()['id']
 assert client.put(f'/apiv2/plants/{pid}',json={'data':{'culture':'Томаты','variety':'Красный','bed':'2'}}).json()['variety']=='Красный'
 obs=client.post('/apiv2/observations',json={'data':{'plant_id':str(pid),'date':'2026-10-16','category':'Полив','description':'Проверка'}})
 assert obs.status_code==201
 assert client.delete(f'/apiv2/plants/{pid}').status_code==409
 assert client.delete(f'/apiv2/observations/{obs.json()["id"]}').status_code==204
 assert client.delete(f'/apiv2/plants/{pid}').status_code==204
 assert client.get('/apiv2/plants').json()==[]
 lotdata={'title':'Партия','culture':'Томаты','quantity':4,'unit':'кг','price':100,'currency':'RUB','status':'Черновик'}
 l=client.post('/apiv2/lots',json={'data':lotdata});assert l.status_code==201
 lid=l.json()['id'];lotdata['status']='Продан';assert client.put(f'/apiv2/lots/{lid}',json={'data':lotdata}).json()['status']=='Продан'
 assert client.delete(f'/apiv2/lots/{lid}').status_code==204
 rec={'title':'Полив','action':'Проверить','status':'Новая'}
 r=client.post('/apiv2/recommendations',json={'data':rec});assert r.status_code==201
 assert client.patch(f'/apiv2/recommendations/{r.json()["id"]}',json={'data':{'status':'Выполнена','outcome':'Проверено'}}).json()['status']=='Выполнена'

def test_inspections_are_not_diagnoses(client):
 for kind in ('soil','plant'):
  r=client.post('/apiv2/analyze/'+kind,files={'file':('im.png',photo(),'image/png')})
  assert r.status_code==200
  assert 'Не определено' in r.json()['diagnosis']
