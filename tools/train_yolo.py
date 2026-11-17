"""Fine-tune YOLO nano on hand-corrected hub crops and export to ONNX.

Needs the optional training deps:  pip install ultralytics   (pulls in PyTorch)

Usage:
    python tools/train_yolo.py dataset/data.yaml [--epochs 60] [--imgsz 448]

dataset/data.yaml (YOLO layout: images/{train,val}, labels/{train,val}):
    path: dataset
    train: images/train
    val: images/val
    names: {0: fuel}

Writes models/fuel.onnx, which the pipeline loads with onnxruntime (no PyTorch at runtime).
"""
import argparse
import shutil
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data")
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--imgsz", type=int, default=448)
    args = ap.parse_args()

    from ultralytics import YOLO

    model = YOLO("yolov8n.pt")
    model.train(data=args.data, epochs=args.epochs, imgsz=args.imgsz, device="cpu",
                degrees=0, flipud=0, hsv_h=0.01, mosaic=1.0, project="runs", name="fuel")
    onnx = Path(model.export(format="onnx", imgsz=args.imgsz, simplify=True))
    dest = Path("models")
    dest.mkdir(exist_ok=True)
    shutil.copy(onnx, dest / "fuel.onnx")
    print("exported", dest / "fuel.onnx")


if __name__ == "__main__":
    main()
