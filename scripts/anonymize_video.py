import argparse
import os
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import torch
from ultralytics import YOLO

from scripts.video_pipeline import run_pipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run anonymization pipeline with YOLOv8 and AES-GCM encryption.")
    parser.add_argument("input", type=Path, help="Path to the input video")
    parser.add_argument("--output", type=Path, default=None, help="Output anonymized video path")
    parser.add_argument(
        "--data-pack",
        type=Path,
        default=None,
        help="Output encrypted metadata pack path (default: alongside output video)",
    )
    parser.add_argument("--model", type=Path, default=Path("yolov8n.pt"), help="YOLOv8 weights path or name")
    parser.add_argument(
        "--device",
        type=str,
        default="auto",
        help="Device to run inference on (auto|cuda|cpu)",
    )
    parser.add_argument(
        "--key",
        type=str,
        default=None,
        help="Hex-encoded AES key (16/24/32 bytes). Generated if omitted.",
    )
    parser.add_argument(
        "--hmac-key",
        type=str,
        default=None,
        help="Hex-encoded HMAC key (32 bytes recommended). Defaults to AES key when omitted.",
    )
    parser.add_argument(
        "--classes",
        type=str,
        nargs="*",
        default=None,
        help="Target classes to anonymize (defaults to person, car, truck, bus, motorcycle, motorbike)",
    )
    parser.add_argument(
        "--manual-roi",
        type=str,
        nargs="*",
        default=None,
        help="Manual ROI boxes defined as x1,y1,x2,y2 in the first frame; can provide multiple.",
    )
    return parser.parse_args()


def resolve_device(device: str) -> str:
    if device == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    return device


def ensure_key(hex_key: Optional[str], label: str, default_len: int = 32) -> bytes:
    if hex_key:
        try:
            key_bytes = bytes.fromhex(hex_key)
        except ValueError as exc:
            raise ValueError(f"无效的 {label} 十六进制字符串") from exc
        if len(key_bytes) not in (16, 24, 32):
            raise ValueError(f"{label} 必须为 16/24/32 字节长度")
        return key_bytes
    key = os.urandom(default_len)
    print(f"生成 {label} (hex): {key.hex()}")
    return key


def ensure_hmac_key(hex_key: Optional[str], fallback: bytes) -> bytes:
    if hex_key:
        try:
            key_bytes = bytes.fromhex(hex_key)
        except ValueError as exc:
            raise ValueError("无效的 HMAC 密钥十六进制字符串") from exc
        if not key_bytes:
            raise ValueError("HMAC 密钥不能为空")
        return key_bytes
    print("未提供 HMAC 密钥，默认与 AES 密钥相同。")
    return fallback


def main() -> None:
    args = parse_args()
    input_path = args.input
    if not input_path.exists():
        raise FileNotFoundError(f"输入视频不存在: {input_path}")

    output_path = args.output or input_path.with_name(f"{input_path.stem}_anonymized.mp4")
    data_pack_path = args.data_pack or output_path.with_name(output_path.stem + "_encrypted_data.pack")

    device = resolve_device(args.device)
    print(f"加载模型 {args.model} 到 {device} 设备")
    model = YOLO(str(args.model))
    model.to(device)

    encryption_key = ensure_key(args.key, "AES 密钥")
    hmac_key = ensure_hmac_key(args.hmac_key, encryption_key)

    target_classes: Optional[Sequence[str]] = args.classes
    if target_classes:
        print(f"仅处理类别: {', '.join(target_classes)}")

    manual_rois: Optional[Sequence[Tuple[int, int, int, int]]] = None
    if args.manual_roi:
        parsed: List[Tuple[int, int, int, int]] = []
        for spec in args.manual_roi:
            parts = spec.split(",")
            if len(parts) != 4:
                raise ValueError(f"无效的 ROI 格式: {spec}，请使用 x1,y1,x2,y2")
            try:
                x1, y1, x2, y2 = (int(p) for p in parts)
            except ValueError as exc:
                raise ValueError(f"ROI 坐标必须为整数: {spec}") from exc
            parsed.append((x1, y1, x2, y2))
        manual_rois = parsed
        print(f"手动跟踪 ROI 个数: {len(parsed)}")

    digest = run_pipeline(
        str(input_path),
        str(output_path),
        model,
        encryption_key,
        str(data_pack_path),
        hmac_key,
        target_classes=target_classes,
        manual_rois=manual_rois,
    )

    print(f"匿名化完成 -> 输出视频: {output_path}")
    print(f"加密数据包: {data_pack_path}")
    print(f"数据包 HMAC: {digest.hex()}")
    print(f"AES 密钥 (hex): {encryption_key.hex()}")
    print(f"HMAC 密钥 (hex): {hmac_key.hex()}")


if __name__ == "__main__":
    main()
