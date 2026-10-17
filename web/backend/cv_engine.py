"""Real HSV / OpenCV heuristic detector. No ML weights, no probabilities.
Algorithm thresholds fixed for 10 synthetic demo images. Natural photos may fail.
"""
import cv2
import numpy as np
import time

COLORS={'ripe':(55,162,0),'unripe':(0,135,255),'uncertain':(145,145,145)}  # BGR

def decode(raw):
    image=cv2.imdecode(np.frombuffer(raw,dtype=np.uint8),cv2.IMREAD_COLOR)
    if image is None: raise ValueError('Файл не удалось декодировать как изображение')
    h,w=image.shape[:2]
    if w*h>24_000_000 or min(w,h)<60: raise ValueError('Размер изображения не поддерживается (от 60 px, до 24 Мп)')
    return image

def detect(image):
    """Return actual image-derived bounding boxes, detection heuristic scores not confidence probabilities."""
    start=time.perf_counter()
    h,w=image.shape[:2]
    scale=min(1.,1200/max(w,h))
    work=cv2.resize(image,None,fx=scale,fy=scale) if scale<1 else image
    H,W=work.shape[:2]; hsv=cv2.cvtColor(work,cv2.COLOR_BGR2HSV)
    hsv=cv2.GaussianBlur(hsv,(3,3),0)
    # Pure colour masks: sufficiently saturated red, and green/yellow-green.
    red=cv2.bitwise_or(cv2.inRange(hsv,(0,95,60),(12,255,255)), cv2.inRange(hsv,(170,95,60),(179,255,255)))
    green=cv2.inRange(hsv,(34,123,63),(76,255,255))
    # Morphological opening removes thin stems and specks; closing restores individual fruit silhouettes.
    kernel=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(7,7))
    objects=[]
    for category,base in [('ripe',red),('unripe',green)]:
        mask=cv2.morphologyEx(base,cv2.MORPH_OPEN,kernel)
        mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(5,5)))
        contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            area=cv2.contourArea(cnt); x,y,bw,bh=cv2.boundingRect(cnt)
            if area<max(190,W*H*0.00027) or bw<17 or bh<17:continue
            aspect=bw/bh
            perimeter=cv2.arcLength(cnt,True)
            circularity=4*np.pi*area/(perimeter*perimeter) if perimeter else 0
            extent=area/(bw*bh)
            # Separate elongated foliage; touching fruit can still be undercounted.
            if not (0.60<=aspect<=1.55 and circularity>=0.48 and extent>=0.48): continue
            # geometric score only, NOT calibrated model confidence
            geometry=round(float(np.clip((circularity-0.48)/0.42,0,1)),2)
            xx=int(x/scale);yy=int(y/scale);ww=int(bw/scale);hh=int(bh/scale)
            objects.append({'id':0,'x':xx,'y':yy,'w':ww,'h':hh,'category':category,'shape_score':geometry})
    # remove overlapping duplicated candidates from two masks
    objects.sort(key=lambda z:z['w']*z['h'],reverse=True)
    selected=[]
    for o in objects:
        if all(iou(o,a)<0.47 for a in selected):selected.append(o)
    selected.sort(key=lambda z:(z['y'],z['x']))
    for i,o in enumerate(selected,1):o['id']=i
    return result(selected,round((time.perf_counter()-start)*1000,2),'opencv_hsv_v1')

def iou(a,b):
    x1=max(a['x'],b['x']); y1=max(a['y'],b['y']);x2=min(a['x']+a['w'],b['x']+b['w']);y2=min(a['y']+a['h'],b['y']+b['h'])
    inter=max(0,x2-x1)*max(0,y2-y1);den=a['w']*a['h']+b['w']*b['h']-inter
    return inter/den if den else 0

def result(objects,ms=0,method='opencv_hsv_v1'):
    n=len(objects);r=sum(o['category']=='ripe' for o in objects);g=sum(o['category']=='unripe' for o in objects)
    return {'objects':objects,'total':n,'ripe':r,'unripe':g,'uncertain':n-r-g,'ripe_pct':round(r/n*100,1) if n else 0,'unripe_pct':round(g/n*100,1) if n else 0,'duration_ms':ms,'method':method,'disclaimer':'Эвристика цвета и формы; shape_score не является вероятностью. Красный цвет не подтверждает безопасность или готовность к продаже.'}

def overlay(image,objects):
    out=image.copy()
    for o in objects:
        x,y,w,h=[int(o[k]) for k in ('x','y','w','h')];cat=o['category']
        color=COLORS.get(cat,COLORS['uncertain']);cv2.rectangle(out,(x,y),(x+w,y+h),color,3)
        label=f"#{o['id']} {cat}";font=cv2.FONT_HERSHEY_SIMPLEX
        (tw,th),_=cv2.getTextSize(label,font,0.55,2)
        ly=max(y-8,th+12)
        cv2.rectangle(out,(x,ly-th-8),(x+tw+10,ly+5),color,-1)
        cv2.putText(out,label,(x+5,ly-2),font,0.55,(255,255,255),2,cv2.LINE_AA)
    return cv2.imencode('.jpg',out,[int(cv2.IMWRITE_JPEG_QUALITY),90])[1].tobytes()

def inspect(image,kind):
    t=time.perf_counter();hsv=cv2.cvtColor(cv2.resize(image,(320,240)),cv2.COLOR_BGR2HSV)
    green=cv2.inRange(hsv,(35,50,35),(90,255,255));yellow=cv2.inRange(hsv,(16,55,55),(35,255,255))
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    if kind=='plant':
        metrics={'visible_green_share_pct':round(float(np.mean(green>0)*100),1),'visible_yellow_share_pct':round(float(np.mean(yellow>0)*100),1)}
        summary='Обнаружены цветовые области на всём снимке, без выделения отдельных листьев; возможна путаница с фоном.'
        checks=['Проверьте, относится ли жёлтый цвет к листьям, а не к освещению или фону.','Уточните освещение, полив, состояние корней и наличие вредителей.']
    else:
        metrics={'mean_brightness_0_255':round(float(np.mean(gray)),1),'surface_contrast_std':round(float(np.std(gray)),1)}
        summary='Измерены общая яркость и неоднородность фотографии; влажность, состав и кислотность почвы не определяются.'
        checks=['Проверьте влажность грунта на глубине и состояние дренажа.','При подозрении на дефицит питания используйте анализ грунта, а не оценку цвета.']
    return {'kind':kind,'method':'opencv_visual_indicators_only','metrics':metrics,'summary':summary,'checks':checks,'duration_ms':round((time.perf_counter()-t)*1000,2),'diagnosis':'Не определено: требуется очный осмотр и дополнительные данные'}
