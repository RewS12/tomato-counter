"""Optional adapter for specialized tomato YOLO weights. NOT installed or enabled by default.
Ultralytics licensing must be checked before distribution/commercial use.
"""
import os
import time
from functools import lru_cache
from pathlib import Path
import cv2
import numpy as np
from fastapi import HTTPException
from backend import cv_engine as cv
ROOT=Path(__file__).resolve().parents[1]
@lru_cache(maxsize=1)
def _model():
    weights=os.getenv('AGROVISION_YOLO_WEIGHTS','models/tomato_best.pt')
    path=Path(weights)
    if not path.is_absolute(): path=ROOT/path
    if not path.is_file(): raise RuntimeError(f'Веса специализированной модели не найдены: {path}')
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError('Пакет ultralytics не установлен: pip install -r requirements-ai.txt') from exc
    return YOLO(str(path))

def category_from_patch(image, box):
    x,y,w,h=[int(box[z]) for z in ('x','y','w','h')]
    roi=image[y:y+h,x:x+w]
    if roi.size==0:return 'uncertain'
    # Analyse centre portion to reduce contribution from surrounding foliage.
    hh,ww=roi.shape[:2]
    sub=roi[int(hh*.20):max(int(hh*.80),1),int(ww*.20):max(int(ww*.80),1)]
    if sub.size==0:sub=roi
    hsv=cv2.cvtColor(sub,cv2.COLOR_BGR2HSV)
    red=np.logical_or(cv2.inRange(hsv,(0,90,55),(12,255,255))>0,cv2.inRange(hsv,(170,90,55),(179,255,255))>0)
    green=cv2.inRange(hsv,(34,90,55),(78,255,255))>0
    total=max(red.size,1); rp=red.sum()/total;gp=green.sum()/total
    # thresholds are heuristics, not learned maturity probabilities
    if rp>=.35 and rp>=gp*1.6:return 'ripe'
    if gp>=.35 and gp>=rp*1.6:return 'unripe'
    return 'uncertain'

def detect_custom(image):
    """Called only when AGROVISION_DETECTOR=yolo. Requires real trained TOMATO weights."""
    try:model=_model()
    except RuntimeError as e:raise HTTPException(503,str(e)) from e
    try:
        started=time.perf_counter()
        predictions=model.predict(source=image,conf=float(os.getenv('AGROVISION_YOLO_CONF','0.30')),verbose=False)
        p=predictions[0]
        names=getattr(p,'names',None) or getattr(model,'names',{})
        objects=[]; height,width=image.shape[:2]
        for box in p.boxes:
            cls_id=int(box.cls[0].item());name=str(names.get(cls_id,'') if isinstance(names,dict) else names[cls_id]).lower()
            # Skip unrelated classes if a multi-class model was supplied.
            if not any(t in name for t in ('tomato','томат','ripe','unripe')):continue
            x1,y1,x2,y2=[int(round(float(v))) for v in box.xyxy[0].tolist()]
            x1=max(0,min(width-1,x1));y1=max(0,min(height-1,y1))
            x2=max(x1+1,min(width,x2));y2=max(y1+1,min(height,y2))
            o={'id':len(objects)+1,'x':x1,'y':y1,'w':x2-x1,'h':y2-y1,'shape_score':None,'detector_score':round(float(box.conf[0].item()),3)}
            if 'unripe' in name or 'green' in name or 'незрел' in name:o['category']='unripe'
            elif 'ripe' in name or 'red' in name or 'зрел' in name:o['category']='ripe'
            else:o['category']=category_from_patch(image,o)
            objects.append(o)
        result=cv.result(objects,round((time.perf_counter()-started)*1000,2),'custom_yolo_tomato_plus_hsv_v1')
        result['disclaimer']='Специализированные веса YOLO: detector_score не калиброванная вероятность. Визуальная зрелость определяется классом/цветовым правилом и требует проверки человеком.'
        return result
    except HTTPException:raise
    except Exception as e:raise HTTPException(503,f'Ошибка YOLO-анализа: {type(e).__name__}') from e
