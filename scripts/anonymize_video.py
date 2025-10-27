import argparse
import json
import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

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
    parser.add_argument(
        "--embed-pack",
        action="store_true",
        help="Embed the generated .pack into the anonymized MP4 as a custom UUID box.",
    )
    parser.add_argument(
        "--embedded-output",
        type=Path,
        default=None,
        help="Optional output path for the MP4 with embedded ROI data (defaults to modifying the output file).",
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
    parser.add_argument(
        "--json-progress",
        action="store_true",
        help="Emit progress events as JSON lines for external integration.",
    )
    parser.add_argument(
        "--style",
        type=str,
        choices=["blur", "mosaic", "pixelate"],
        default="blur",
        help="Obfuscation style to apply inside detections/ROIs (default: blur).",
    )
    parser.add_argument(
        "--disable-detector",
        action="store_true",
        help="Disable YOLO 自动检测，仅保留手动 ROI 处理。",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Worker thread count for frame processing (default: 1).",
    )
    return parser.parse_args()


def resolve_device(device: str) -> str:
    if device == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    return device


def ensure_key(hex_key: Optional[str], label: str, default_len: int = 32, logger: Optional[Callable[[str], None]] = None) -> bytes:
    if hex_key:
        try:
            key_bytes = bytes.fromhex(hex_key)
        except ValueError as exc:
            raise ValueError(f"无效的 {label} 十六进制字符串") from exc
        if len(key_bytes) not in (16, 24, 32):
            raise ValueError(f"{label} 必须为 16/24/32 字节长度")
        return key_bytes
    key = os.urandom(default_len)
    if logger:
        logger(f"生成 {label} (hex): {key.hex()}")
    return key


def ensure_hmac_key(hex_key: Optional[str], fallback: bytes, logger: Optional[Callable[[str], None]] = None) -> bytes:
    if hex_key:
        try:
            key_bytes = bytes.fromhex(hex_key)
        except ValueError as exc:
            raise ValueError("无效的 HMAC 密钥十六进制字符串") from exc
        if not key_bytes:
            raise ValueError("HMAC 密钥不能为空")
        return key_bytes
    if logger:
        logger("未提供 HMAC 密钥，默认与 AES 密钥相同。")
    return fallback


@dataclass
class AnonymizationRequest:
    input_path: Path
    output_path: Path
    data_pack_path: Path
    device: str = "auto"
    classes: Optional[Sequence[str]] = None
    manual_rois: Optional[Sequence[Tuple[int, int, int, int]]] = None
    aes_key_hex: Optional[str] = None
    hmac_key_hex: Optional[str] = None
    style: str = "blur"
    disable_detector: bool = False
    worker_count: int = 1
    embed_pack: bool = False
    embedded_output_path: Optional[Path] = None


def parse_manual_roi_args(values: Optional[Sequence[str]]) -> Optional[List[Tuple[int, int, int, int]]]:
    if not values:
        return None
    parsed: List[Tuple[int, int, int, int]] = []
    for spec in values:
        parts = spec.split(",")
        if len(parts) != 4:
            raise ValueError(f"无效的 ROI 格式: {spec}，请使用 x1,y1,x2,y2")
        try:
            x1, y1, x2, y2 = (int(p) for p in parts)
        except ValueError as exc:
            raise ValueError(f"ROI 坐标必须为整数: {spec}") from exc
        parsed.append((x1, y1, x2, y2))
    return parsed


def _normalize_manual_rois(
    rois: Optional[Sequence[Tuple[int, int, int, int]]]
) -> Optional[List[Tuple[int, int, int, int]]]:
    if not rois:
        return None
    normalized: List[Tuple[int, int, int, int]] = []
    for roi in rois:
        x1, y1, x2, y2 = (int(value) for value in roi)
        normalized.append((x1, y1, x2, y2))
    return normalized


def run_anonymization(
    model: YOLO,
    request: AnonymizationRequest,
    status_callback: Optional[Callable[[str, Dict[str, object]], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    logger: Optional[Callable[[str], None]] = None,
) -> Dict[str, object]:
    device = resolve_device(request.device)
    model.to(device)

    encryption_key = ensure_key(request.aes_key_hex, "AES 密钥", logger=logger)
    hmac_key = ensure_hmac_key(request.hmac_key_hex, encryption_key, logger=logger)

    target_classes: Optional[Sequence[str]]
    if request.classes is None:
        target_classes = None
    else:
        target_classes = list(request.classes)
        if logger and target_classes:
            logger(f"仅处理类别: {', '.join(target_classes)}")
        elif logger and not target_classes:
            logger("未选择自动检测类别，将仅处理手动区域。")

    manual_rois = _normalize_manual_rois(request.manual_rois)
    if logger and manual_rois:
        logger(f"手动跟踪 ROI 个数: {len(manual_rois)}")

    digest = run_pipeline(
        str(request.input_path),
        str(request.output_path),
        model,
        encryption_key,
        str(request.data_pack_path),
        hmac_key,
        target_classes=target_classes,
        manual_rois=manual_rois,
        status_callback=status_callback,
        style=request.style,
        enable_detection=not request.disable_detector and (target_classes is None or len(target_classes) > 0),
        worker_count=max(1, request.worker_count),
        cancel_event=cancel_event,
        embed_pack=request.embed_pack,
        embedded_output_path=str(request.embedded_output_path) if request.embedded_output_path else None,
    )

    embedded_video_path: Optional[Path] = None
    if request.embed_pack:
        embedded_video_path = request.embedded_output_path or request.output_path

    result: Dict[str, object] = {
        "output": str(request.output_path),
        "data_pack": str(request.data_pack_path),
        "digest": digest,
        "aes_key": encryption_key,
        "hmac_key": hmac_key,
    }

    if embedded_video_path is not None:
        result["embedded_output"] = str(embedded_video_path)

    return result


def main() -> None:
    args = parse_args()
    input_path = args.input
    if not input_path.exists():
        raise FileNotFoundError(f"输入视频不存在: {input_path}")

    output_path = args.output or input_path.with_name(f"{input_path.stem}_anonymized.mp4")
    data_pack_path = args.data_pack or output_path.with_name(output_path.stem + "_encrypted_data.pack")

    json_mode = bool(args.json_progress)

    def emit_event(event: str, data: Optional[Dict[str, object]] = None) -> None:
        payload = {"event": event}
        if data:
            payload.update(data)
        print(json.dumps(payload, ensure_ascii=False), flush=True)

    def log(message: str) -> None:
        if json_mode:
            emit_event("log", {"message": message})
        else:
            print(message)

    classes = list(args.classes) if args.classes is not None else None
    manual_rois = parse_manual_roi_args(args.manual_roi)

    request = AnonymizationRequest(
        input_path=input_path,
        output_path=output_path,
        data_pack_path=data_pack_path,
        device=args.device,
        classes=classes,
        manual_rois=manual_rois,
        aes_key_hex=args.key,
        hmac_key_hex=args.hmac_key,
        style=args.style,
        disable_detector=args.disable_detector,
        worker_count=max(1, args.workers),
        embed_pack=bool(args.embed_pack),
        embedded_output_path=args.embedded_output,
    )

    log(f"加载模型 {args.model} 到 {resolve_device(args.device)} 设备")
    model = YOLO(str(args.model))

    def status_callback(event: str, data: Dict[str, object]) -> None:
        if json_mode:
            emit_event(event, data)
        elif event == "progress":
            processed = data.get("processed", 0)
            total = data.get("total_frames", 0) or 0
            percent = 0.0
            if total:
                percent = float(processed) / float(total) * 100.0
            print(f"进度: {processed}/{total or '?'} ({percent:.2f}%)")

    try:
        result = run_anonymization(
            model,
            request,
            status_callback=status_callback,
            cancel_event=None,
            logger=log,
        )
    except Exception as exc:  # pragma: no cover - integration error path
        if json_mode:
            emit_event("error", {"message": str(exc)})
        raise

    digest_bytes = result["digest"]
    aes_key = result["aes_key"]
    hmac_key = result["hmac_key"]
    embedded_output = result.get("embedded_output")

    if json_mode:
        emit_event(
            "completed",
            {
                "output": str(output_path),
                "data_pack": str(data_pack_path),
                "digest": digest_bytes.hex(),
                "aes_key": aes_key.hex(),
                "hmac_key": hmac_key.hex(),
                "embedded_output": embedded_output,
            },
        )
    else:
        print(f"匿名化完成 -> 输出视频: {output_path}")
        print(f"加密数据包: {data_pack_path}")
        print(f"数据包 HMAC: {digest_bytes.hex()}")
        print(f"AES 密钥 (hex): {aes_key.hex()}")
        print(f"HMAC 密钥 (hex): {hmac_key.hex()}")
        if embedded_output:
            print(f"嵌入数据的视频: {embedded_output}")


if __name__ == "__main__":
    main()
