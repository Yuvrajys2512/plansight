"""Fine-tune cubicasa_objects v1 on the v2 dataset (tiles + style aug). Runs on the Verda box."""
from ultralytics import YOLO

m = YOLO("/data/runs/cubicasa_m1280/weights/best.pt")
m.train(data="/data/out/yolo_v2/data.yaml", imgsz=1280, epochs=30, batch=16, workers=24, cache=False,
        project="/data/runs", name="cubicasa_v2", exist_ok=True, fliplr=0.5, flipud=0.5, degrees=0,
        scale=0.5, hsv_h=0.015, hsv_s=0.5, hsv_v=0.4, mosaic=1.0, close_mosaic=5, cos_lr=True,
        optimizer="AdamW", lr0=0.0002, lrf=0.1, warmup_epochs=1, patience=10, plots=True, amp=True)
