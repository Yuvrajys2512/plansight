#!/bin/sh
# (re)start the v2 fine-tune + watcher on the Verda box. Run detached: nohup sh restart_v2.sh &
cd /root
pkill -f after_v2.sh
pkill -INT -f "python train_v2"
sleep 20
pkill -9 -f "python train_v2"
sleep 5
rm -rf /data/runs/cubicasa_v2
nohup /root/yolo/bin/python train_v2.py > train_v2.log 2>&1 < /dev/null &
sleep 5
nohup sh ./after_v2.sh > after_v2.log 2>&1 < /dev/null &
echo restarted
