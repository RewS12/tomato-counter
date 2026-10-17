from pathlib import Path
from uuid import uuid4
import json
import mimetypes
import os
import base64
import secrets
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict
import cv2
from backend import db,cv_engine as cv

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=ROOT/'runtime'; IMAGES=RUNTIME/'images'; FRONTEND=ROOT/'frontend'
IMAGES.mkdir(exist_ok=True,parents=True);db.init()
app=FastAPI(title='AgroVision — демо',version='1.1.0',description='OpenCV HSV heuristic (optional custom YOLO weights). Not agronomic diagnosis.')
AUTH_REQUIRED=os.getenv('AGROVISION_REQUIRE_AUTH','0')=='1'
BASIC_USER=os.getenv('AGROVISION_BASIC_USER','')
BASIC_PASSWORD=os.getenv('AGROVISION_BASIC_PASSWORD','')
if AUTH_REQUIRED and (not BASIC_USER or len(BASIC_PASSWORD)<12 or 'CHANGE-THIS' in BASIC_PASSWORD):
 raise RuntimeError('Для защищённого запуска установите AGROVISION_BASIC_USER и AGROVISION_BASIC_PASSWORD длиной от 12 символов')

# Лендинг, статика и демо-примеры публичны; приложение и API — под Basic Auth.
PROTECTED_PREFIXES=('/app','/apiv2','/media','/docs','/redoc','/openapi.json')

@app.middleware('http')
async def optional_basic_auth(request:Request, call_next):
 if AUTH_REQUIRED and request.url.path.startswith(PROTECTED_PREFIXES):
  header=request.headers.get('authorization','')
  valid=False
  if header.lower().startswith('basic '):
   try:
    b=base64.b64decode(header.split(' ',1)[1],validate=True).decode('utf-8')
    name,passw=b.split(':',1)
    valid=secrets.compare_digest(name,BASIC_USER) and secrets.compare_digest(passw,BASIC_PASSWORD)
   except (ValueError,UnicodeError):pass
  if not valid:
   return Response('Требуется авторизация',status_code=401,headers={'WWW-Authenticate':'Basic realm="AgroVision"','Cache-Control':'no-store'})
 response=await call_next(request)
 response.headers['X-Content-Type-Options']='nosniff'
 response.headers['Referrer-Policy']='no-referrer'
 response.headers['X-Frame-Options']='DENY'
 return response
app.mount('/static',StaticFiles(directory=str(FRONTEND)),name='frontend')
app.mount('/media',StaticFiles(directory=str(IMAGES)),name='media')
app.mount('/samples',StaticFiles(directory=str(ROOT/'data')),name='samples')
MAX_UPLOAD=8*1024*1024

class Data(BaseModel):
 model_config=ConfigDict(extra='forbid')
 data:dict

async def save_upload(file:UploadFile):
 if (file.content_type or '').lower() not in ('image/jpeg','image/png','image/webp'):
  raise HTTPException(415,'Разрешены JPG, PNG и WebP')
 raw=await file.read(MAX_UPLOAD+1)
 if not raw or len(raw)>MAX_UPLOAD:raise HTTPException(413,'Изображение пустое или больше 8 МБ')
 try:image=cv.decode(raw)
 except ValueError as e:raise HTTPException(422,str(e)) from e
 ext={"image/jpeg":"jpg","image/png":"png","image/webp":"webp"}[file.content_type.lower()]
 fname=f'{uuid4().hex}.{ext}';(IMAGES/fname).write_bytes(raw)
 return image,'/media/'+fname

def write_overlay(image,result):
 name=f'{uuid4().hex}-overlay.jpg';(IMAGES/name).write_bytes(cv.overlay(image,result['objects']))
 return '/media/'+name

def clean_objects(objs,image):
 h,w=image.shape[:2];out=[]
 if len(objs)>400:raise HTTPException(422,'Слишком много объектов')
 for i,o in enumerate(objs,1):
  try:x,y,bw,bh=[int(o[z]) for z in ('x','y','w','h')];cat=o['category']
  except (KeyError,ValueError,TypeError) as e:raise HTTPException(422,'Неверные координаты') from e
  if cat not in ('ripe','unripe','uncertain') or min(x,y)<0 or min(bw,bh)<4 or x+bw>w or y+bh>h:raise HTTPException(422,'Недопустимая рамка или категория')
  out.append({'id':i,'x':x,'y':y,'w':bw,'h':bh,'category':cat,'shape_score':None})
 return out

def get_active_detector_label():
 mode=os.getenv('AGROVISION_DETECTOR','opencv').lower()
 return 'custom-yolo' if mode=='yolo' else 'opencv-hsv'

def detect_selected(image):
 mode=os.getenv('AGROVISION_DETECTOR','opencv').lower()
 if mode=='opencv':return cv.detect(image)
 if mode=='yolo':
  from backend.yolo_adapter import detect_custom
  return detect_custom(image)
 raise HTTPException(503,'Неизвестный AGROVISION_DETECTOR')

@app.get('/')
def landing():return FileResponse(FRONTEND/'index.html')
@app.get('/app')
def application():return FileResponse(FRONTEND/'app.html')
@app.get('/sw.js')
def service_worker():return FileResponse(FRONTEND/'sw.js',media_type='text/javascript')
@app.get('/apiv2/health')
def health():return {'status':'ok','storage':'sqlite','detector':get_active_detector_label(),'authentication':AUTH_REQUIRED,'demo':True}
@app.post('/apiv2/analyze/fruits')
async def analyze_fruits(file:UploadFile=File(...),plant_id:str|None=Form(None)):
 image,original_url=await save_upload(file)
 res=detect_selected(image);overlay_url=write_overlay(image,res)
 uid=uuid4().hex;db.add_analysis(uid,original_url,overlay_url,res)
 return {'id':uid,'original_url':original_url,'overlay_url':overlay_url,'plant_id':plant_id,'width':image.shape[1],'height':image.shape[0],**res}
@app.get('/apiv2/analyses')
def analyses_list():return db.list_analyses()
@app.post('/apiv2/upload')
async def upload_only(file:UploadFile=File(...)):
 image,url=await save_upload(file)
 return {'url':url,'width':image.shape[1],'height':image.shape[0]}
@app.get('/apiv2/analyses/{id}')
def analysis_get(id:str):
 item=db.get_analysis(id)
 if not item:raise HTTPException(404,'Анализ не найден')
 return {'id':id,'original_url':item['original_url'],'overlay_url':item['overlay_url'],**item['result']}
@app.put('/apiv2/analyses/{id}/objects')
def analysis_edit(id:str,payload:Data):
 item=db.get_analysis(id)
 if not item:raise HTTPException(404,'Анализ не найден')
 objs=payload.data.get('objects')
 if not isinstance(objs,list):raise HTTPException(422,'Ожидается список objects')
 path=IMAGES/Path(item['original_url']).name
 image=cv.decode(path.read_bytes());objects=clean_objects(objs,image)
 res=cv.result(objects,item['result']['duration_ms'],method='manual_revision_of_'+item['result']['method'])
 overlay_url=write_overlay(image,res);db.update_analysis(id,res,overlay_url)
 return {'id':id,'original_url':item['original_url'],'overlay_url':overlay_url,**res}
@app.post('/apiv2/analyze/plant')
async def analyze_plant(file:UploadFile=File(...)):
 image,url=await save_upload(file);return {'photo_url':url,**cv.inspect(image,'plant')}
@app.post('/apiv2/analyze/soil')
async def analyze_soil(file:UploadFile=File(...)):
 image,url=await save_upload(file);return {'photo_url':url,**cv.inspect(image,'soil')}

ALLOWED={
 'plants':('culture','variety','location','bed','planted_at','description'),
 'observations':('plant_id','date','category','description','action','outcome','photo_url','analysis_id'),
 'lots':('title','culture','quantity','unit','price','currency','status','buyer','description','photo_url'),
 'recommendations':('title','evidence','explanation','action','certainty','verify','status','outcome','plant_id'),
}

def validate(name,d):
 if not isinstance(d,dict):raise HTTPException(422,'Ожидается объект')
 if any(k not in ALLOWED[name] for k in d):raise HTTPException(422,'Неизвестное поле')
 if name=='plants':
  if not str(d.get('culture') or '').strip():raise HTTPException(422,'Укажите культуру')
 if name=='lots':
  for required in ('title','culture','unit','currency','status'):
   if not str(d.get(required) or '').strip():raise HTTPException(422,'Не заполнено поле '+required)
  if d['status'] not in ('Черновик','Готов к продаже','Зарезервирован','Продан','Отменён'):raise HTTPException(422,'Недопустимый статус')
  try:d['quantity']=float(d['quantity']);d['price']=float(d['price'])
  except (ValueError,KeyError,TypeError):raise HTTPException(422,'Количество и цена должны быть числом')
  if d['quantity']<=0 or d['price']<0:raise HTTPException(422,'Количество > 0 и цена ≥ 0')
 if name=='observations':
  if not d.get('date') or not d.get('category'):raise HTTPException(422,'Укажите дату и категорию')
  if d.get('plant_id') and not db.one('plants',d['plant_id']):raise HTTPException(422,'Растение не найдено')
  if d.get('analysis_id') and not db.get_analysis(d['analysis_id']):raise HTTPException(422,'Анализ не найден')
 return d

@app.get('/apiv2/plants')
def plants():return db.all_rows('plants')
@app.post('/apiv2/plants',status_code=201)
def create_plant(payload:Data):return db.save('plants',validate('plants',payload.data))
@app.get('/apiv2/plants/{id}')
def plant(id:int):return get_one('plants',id)
@app.put('/apiv2/plants/{id}')
def update_plant(id:int,payload:Data):return change('plants',id,payload.data)
@app.delete('/apiv2/plants/{id}',status_code=204)
def delete_plant(id:int):
 if any(str(x.get('plant_id'))==str(id) for x in db.all_rows('observations')):
  raise HTTPException(409,'Сначала удалите или перепривяжите наблюдения этого растения')
 return destroy('plants',id)
@app.get('/apiv2/observations')
def observations():return db.all_rows('observations')
@app.post('/apiv2/observations',status_code=201)
def create_observation(payload:Data):return db.save('observations',validate('observations',payload.data))
@app.get('/apiv2/observations/{id}')
def observation(id:int):return get_one('observations',id)
@app.put('/apiv2/observations/{id}')
def update_observation(id:int,payload:Data):return change('observations',id,payload.data)
@app.delete('/apiv2/observations/{id}',status_code=204)
def delete_observation(id:int):return destroy('observations',id)
@app.get('/apiv2/recommendations')
def recommendations():return db.all_rows('recommendations')
@app.post('/apiv2/recommendations',status_code=201)
def create_recommendation(payload:Data):return db.save('recommendations',validate('recommendations',payload.data))
@app.patch('/apiv2/recommendations/{id}')
def patch_recommendation(id:int,payload:Data):return change('recommendations',id,payload.data,patch=True)
@app.delete('/apiv2/recommendations/{id}',status_code=204)
def delete_recommendation(id:int):return destroy('recommendations',id)
@app.get('/apiv2/lots')
def lots():return db.all_rows('lots')
@app.post('/apiv2/lots',status_code=201)
def create_lot(payload:Data):return db.save('lots',validate('lots',payload.data))
@app.get('/apiv2/lots/{id}')
def lot(id:int):return get_one('lots',id)
@app.put('/apiv2/lots/{id}')
def update_lot(id:int,payload:Data):return change('lots',id,payload.data)
@app.delete('/apiv2/lots/{id}',status_code=204)
def delete_lot(id:int):return destroy('lots',id)

def get_one(name,id):
 item=db.one(name,id)
 if not item:raise HTTPException(404,'Запись не найдена')
 return item

def change(name,id,d,patch=False):
 old=get_one(name,id)
 merged={k:old.get(k) for k in ALLOWED[name]};merged.update(d)
 validate(name,merged)
 result=db.save(name,d if patch else merged,id)
 return result

def destroy(name,id):
 if not db.delete(name,id):raise HTTPException(404,'Запись не найдена')
 return Response(status_code=204)

KNOWLEDGE=[
 {'id':1,'topic':'Полив','title':'Как проверять необходимость полива','body':'Ориентируйтесь на влажность грунта в зоне корней, погоду, стадию развития и дренаж. Цвет поверхности грунта на фото недостаточен для решения. Поливайте с учётом условий участка.','checks':['Проверить грунт на глубине','Зафиксировать дату и объём полива','Проверить дренаж']},
 {'id':2,'topic':'Освещение','title':'Когда томатам не хватает света','body':'При вытягивании побегов и слабом развитии проверьте фактическую освещённость и затенение. Один снимок не устанавливает причину.','checks':['Сравнить освещённость в разные часы','Проверить затенение','Сделать повторное фото']},
 {'id':3,'topic':'Листья','title':'Пожелтение и пятна: порядок осмотра','body':'У изменения окраски много причин: освещение, вода, питание, температура, вредители и заболевания. Проверьте распределение симптомов на растении, влажность и условия.','checks':['Осмотреть обе стороны листа','Отметить поражённую часть куста','При необходимости проконсультироваться с агрономом']},
 {'id':4,'topic':'Микроклимат','title':'Проветривание теплицы','body':'Решение о проветривании принимайте по реальным показаниям температуры и влажности, а не только по фотографии.','checks':['Снять показания термометра','Проверить влажность воздуха','Уточнить фазу роста']},
 {'id':5,'topic':'Подкормка','title':'Как избежать необоснованной подкормки','body':'Не выбирайте удобрение по цвету листьев на одном снимке. Уточните историю внесений, pH, состав воды и результаты анализа грунта при необходимости.','checks':['Проверить журнал внесений','Измерить pH подходящим методом','Согласовать коррекцию с агрономом']},
 {'id':6,'topic':'Урожай','title':'Подготовка томатов к реализации','body':'Цвет позволяет предварительно выделить кандидатов на осмотр. Товарный сорт, массу, качество, безопасность и сроки хранения нужно подтверждать отдельно.','checks':['Проверить целостность вручную','Взвесить партию','Подтвердить товарную категорию']},
 {'id':7,'topic':'Рассада','title':'Осмотр молодых растений','body':'Сопоставляйте рост, форму листьев, свет и режим полива. Сравнения полезны при сопоставимом ракурсе и освещении.','checks':['Зафиксировать дату посадки','Сделать фото с той же точки','Отметить изменения']},
 {'id':8,'topic':'Почва','title':'Почему фото не показывает плодородие','body':'Фотография поверхности не определяет азот, фосфор, калий, кислотность и влажность корней. Для проверки нужны измерения и история участка.','checks':['Уточнить тип грунта','Проверить дренаж','При необходимости провести анализ грунта']},
]
@app.get('/apiv2/knowledge')
def knowledge(query:str='',topic:str=''):
 q=query.casefold().strip();t=topic.casefold().strip()
 return [a for a in KNOWLEDGE if (not q or q in (a['title']+' '+a['body']+' '+a['topic']).casefold()) and (not t or t==a['topic'].casefold())]
@app.get('/apiv2/demo')
def demo():
 j=json.loads((ROOT/'data'/'annotations'/'ground_truth.json').read_text(encoding='utf-8'))
 return [{**{'id':i['id'],'url':'/samples/'+i['file'].replace('data/',''),'split':i['split'],'ground_truth_count':len(i['ground_truth'])}} for i in j['items']]
@app.get('/apiv2/evaluation')
def evaluation():
 p=ROOT/'data'/'evaluation.json'
 if not p.exists():return {'status':'not_measured','reason':'Запустите python -m backend.evaluate'}
 return json.loads(p.read_text(encoding='utf-8'))
@app.get('/apiv2/export')
def export_all():return {'demo_notice':'Экспорт локальной однопользовательской базы. Не загружайте сюда чувствительную информацию.','plants':db.all_rows('plants'),'observations':db.all_rows('observations'),'recommendations':db.all_rows('recommendations'),'lots':db.all_rows('lots')}
