#!/bin/sh
# watcher: wait for training (max 3.5 h), export ONNX + test-split count eval, then power off.
cd /root
START=$(date +%s)
while pgrep -f "train_v2.py" >/dev/null; do
  if [ $(( $(date +%s) - START )) -gt 12600 ]; then pkill -INT -f train_v2.py; sleep 120; pkill -9 -f train_v2.py; fi
  sleep 30
done
W=/data/runs/cubicasa_v2/weights/best.pt
[ -f $W ] || cp /data/runs/cubicasa_v2/weights/last.pt $W
/root/yolo/bin/python export.py /data/runs/cubicasa_v2 cubicasa_objects_v2 1280 > /root/export_v2.log 2>&1
/root/yolo/bin/python eval_cubicasa_det.py objects $W /data/out/yolo /root/cubicasa_gold.json 1280 > /root/eval_v2.md 2>/root/eval_v2.err
touch /root/V2_DONE
sleep 1800
shutdown -h now
