import argparse
import sys
import tempfile
from pathlib import Path
from urllib.request import urlretrieve

import torch
from ultralytics import YOLO


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run YOLOv8 detection to validate GPU setup.")
    parser.add_argument(
        "--image",
        type=Path,
        help="Path to a local image file. If omitted, a sample image will be downloaded automatically.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="yolov8n.pt",
        help="YOLOv8 weights to load (defaults to yolov8n.pt).",
    )
    return parser.parse_args()


def download_sample_image() -> Path:
    sample_url = "https://ultralytics.com/images/zidane.jpg"
    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
    tmp_path = Path(tmp_file.name)
    tmp_file.close()
    try:
        urlretrieve(sample_url, tmp_path)
    except Exception as err:  # pragma: no cover
        print(f"无法下载示例图片: {err}", file=sys.stderr)
        raise
    return tmp_path


def load_image_path(image_arg: Path | None) -> Path:
    if image_arg:
        if not image_arg.exists():
            print(f"指定的图片不存在: {image_arg}", file=sys.stderr)
            sys.exit(1)
        return image_arg
    print("未提供图片路径，正在下载示例图片...")
    return download_sample_image()


def run_detection(image_path: Path, model_weights: str) -> None:
    cuda_available = torch.cuda.is_available()
    if not cuda_available:
        print("警告：当前环境未检测到可用的 CUDA 设备，将在 CPU 上运行。", file=sys.stderr)
    device = "cuda" if cuda_available else "cpu"

    model = YOLO(model_weights)
    model.to(device)

    results = model(str(image_path))
    if not results:
        print("未得到任何检测结果。", file=sys.stderr)
        return

    names = model.model.names if hasattr(model.model, "names") else model.names
    print(f"检测图片: {image_path}")
    for res in results:
        if res.boxes is None:
            continue
        for box in res.boxes:
            cls_id = int(box.cls.item())
            conf = float(box.conf.item())
            xyxy = box.xyxy.view(-1).tolist()
            label = names.get(cls_id, str(cls_id)) if isinstance(names, dict) else names[cls_id]
            print(
                f"类别: {label}, 置信度: {conf:.3f}, 边界框: [{xyxy[0]:.1f}, {xyxy[1]:.1f}, {xyxy[2]:.1f}, {xyxy[3]:.1f}]"
            )


def main() -> None:
    args = parse_args()
    image_path = load_image_path(args.image)
    run_detection(image_path, args.model)


if __name__ == "__main__":
    main()
