from backend.evaluate import evaluate

def test_holdout_three_real_computations():
 result=evaluate()
 assert result['checked']==3
 assert result['gt_objects']>0
 assert len(result['per_image'])==3
 assert result['tp']+result['fn']==result['gt_objects']
 assert result['tp']+result['fp']==result['detected_objects']
 assert all('duration_ms' in row for row in result['per_image'])
