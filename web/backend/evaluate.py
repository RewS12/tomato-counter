"""Reproducible evaluation on 3 HELD-OUT SYNTHETIC files. Run from project root."""
import json,statistics
from pathlib import Path
import cv2
from .cv_engine import detect,iou
ROOT=Path(__file__).resolve().parents[1]

def evaluate():
 data=json.loads((ROOT/'data/annotations/ground_truth.json').read_text(encoding='utf8'))
 rows=[];tp=fp=fn=cat_correct=0;gt_count=det_count=0;matrix={a:{b:0 for b in ('ripe','unripe','uncertain')} for a in ('ripe','unripe')}
 for entry in data['items']:
  if entry['split']!='validation':continue
  im=cv2.imread(str(ROOT/entry['file']))
  if im is None:raise RuntimeError('Missing '+entry['file'])
  result=detect(im);pred=result['objects'];gt=entry['ground_truth']
  # one-to-one greedy, descending IoU, threshold .5
  potential=sorted([(iou(a,b),i,j) for i,a in enumerate(gt) for j,b in enumerate(pred)],reverse=True)
  matched_g=set();matched_p=set();match=[]
  for score,i,j in potential:
   if score<.5:break
   if i not in matched_g and j not in matched_p:
    matched_g.add(i);matched_p.add(j);match.append((i,j,round(score,3)))
    matrix[gt[i]['category']][pred[j]['category']]+=1
    if gt[i]['category']==pred[j]['category']:cat_correct+=1
  tp+=len(match);fp+=len(pred)-len(match);fn+=len(gt)-len(match);gt_count+=len(gt);det_count+=len(pred)
  rows.append({'image':entry['file'].split('/')[-1],'gt':len(gt),'detected':len(pred),'absolute_count_error':abs(len(pred)-len(gt)),'matched':len(match),'false_positive':len(pred)-len(match),'false_negative':len(gt)-len(match),'duration_ms':result['duration_ms'],'matches':match})
 score={'status':'measured_on_synthetic_validation_only','method':'opencv_hsv_v1','matching':'greedy one-to-one IoU >= 0.5','dataset':'Three separate generated synthetic images; NOT representative of real greenhouse performance', 'checked':len(rows),'gt_objects':gt_count,'detected_objects':det_count,'tp':tp,'fp':fp,'fn':fn,'precision':round(tp/(tp+fp),4) if tp+fp else None,'recall':round(tp/(tp+fn),4) if tp+fn else None,'mae_count':round(statistics.mean(r['absolute_count_error'] for r in rows),3) if rows else None,'classification_accuracy_on_matched':round(cat_correct/tp,4) if tp else None,'confusion_matrix':matrix,'per_image':rows,'avg_duration_ms':round(statistics.mean(r['duration_ms'] for r in rows),2) if rows else None}
 (ROOT/'data/evaluation.json').write_text(json.dumps(score,ensure_ascii=False,indent=2),encoding='utf8')
 return score
if __name__=='__main__':print(json.dumps(evaluate(),ensure_ascii=False,indent=2))
