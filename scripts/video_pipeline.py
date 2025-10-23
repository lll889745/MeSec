import os
import sys
import threading
from pathlib import Path
from queue import Queue
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import cv2
import numpy as np
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from scripts.data_pack import DataPackWriter


FrameItem = Tuple[int, np.ndarray]
ProcessedItem = Tuple[int, np.ndarray, List[Dict[str, object]]]


def _create_tracker() -> cv2.Tracker:
    if hasattr(cv2, "TrackerCSRT_create"):
        return cv2.TrackerCSRT_create()
    if hasattr(cv2, "legacy") and hasattr(cv2.legacy, "TrackerCSRT_create"):
        return cv2.legacy.TrackerCSRT_create()
    raise RuntimeError("当前 OpenCV 安装不支持 CSRT 跟踪器，请安装 opencv-contrib-python >= 4.5")


def producer(video_path: str, frame_queue: Queue, sentinel: Optional[object] = None, worker_count: int = 1) -> None:
    """Read frames from a video file and enqueue them for processing."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"无法打开视频文件: {video_path}")

    frame_index = 0
    try:
        while True:
            success, frame = cap.read()
            if not success:
                break
            frame_queue.put((frame_index, frame))
            frame_index += 1
    finally:
        cap.release()
        # signal no more frames
        for _ in range(worker_count):
            frame_queue.put(sentinel)


def encrypt_roi(roi: np.ndarray, key: bytes) -> bytes:
    """Encrypt ROI with AES-256-GCM returning nonce|ciphertext|tag."""
    if len(key) not in (16, 24, 32):
        raise ValueError("加密密钥长度必须为 16/24/32 字节")

    nonce = os.urandom(12)
    contiguous = np.ascontiguousarray(roi)
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    ciphertext = encryptor.update(contiguous.tobytes()) + encryptor.finalize()
    return nonce + ciphertext + encryptor.tag


def _apply_gaussian_blur(frame: np.ndarray, bbox: Tuple[int, int, int, int]) -> None:
    x1, y1, x2, y2 = bbox
    roi = frame[y1:y2, x1:x2]
    if roi.size == 0:
        return
    ksize = max(5, (min(roi.shape[0], roi.shape[1]) // 2) * 2 + 1)
    blurred = cv2.GaussianBlur(roi, (ksize, ksize), 0)
    frame[y1:y2, x1:x2] = blurred


def _apply_mosaic(frame: np.ndarray, bbox: Tuple[int, int, int, int], cell_size: int = 14) -> None:
    x1, y1, x2, y2 = bbox
    roi = frame[y1:y2, x1:x2]
    if roi.size == 0:
        return
    h, w = roi.shape[:2]
    grid_w = max(1, w // cell_size)
    grid_h = max(1, h // cell_size)
    small = cv2.resize(roi, (grid_w, grid_h), interpolation=cv2.INTER_LINEAR)
    mosaic = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)
    frame[y1:y2, x1:x2] = mosaic


def _apply_pixelate(frame: np.ndarray, bbox: Tuple[int, int, int, int], scale: float = 0.15) -> None:
    x1, y1, x2, y2 = bbox
    roi = frame[y1:y2, x1:x2]
    if roi.size == 0:
        return
    h, w = roi.shape[:2]
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    small = cv2.resize(roi, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    pixelated = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)
    frame[y1:y2, x1:x2] = pixelated


def apply_obfuscation(frame: np.ndarray, bbox: Tuple[int, int, int, int], style: str) -> None:
    style_normalized = style.lower()
    if style_normalized == "mosaic":
        _apply_mosaic(frame, bbox)
        return
    if style_normalized == "pixelate":
        _apply_pixelate(frame, bbox)
        return
    _apply_gaussian_blur(frame, bbox)


def _safe_callback(callback: Optional[Callable[[str, Dict[str, Any]], None]], event: str, data: Dict[str, Any]) -> None:
    if not callback:
        return
    try:
        callback(event, data)
    except Exception as error:  # pragma: no cover - defensive logging
        print(f"[status_callback_error] {event}: {error}", file=sys.stderr)


def worker(
    frame_queue: Queue,
    processed_queue: Queue,
    model,
    encryption_key: bytes,
    sentinel: Optional[object] = None,
    target_classes: Optional[Sequence[str]] = None,
    manual_rois: Optional[Sequence[Tuple[int, int, int, int]]] = None,
    status_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    style: str = "blur",
    enable_detection: bool = True,
) -> None:
    """Consume raw frames, run detection/anonymization, and enqueue results."""
    default_classes = ("person", "car", "truck", "bus", "motorcycle", "motorbike")
    if target_classes is None:
        sensitive_classes = set(default_classes)
    else:
        sensitive_classes = set(target_classes)
    style_mode = style.lower() if style else "blur"
    tracker_entries: List[Dict[str, object]] = []
    trackers_initialized = False

    while True:
        item = frame_queue.get()
        try:
            if item is sentinel:
                break

            if item is None:
                continue

            frame_index, frame = item

            processed_frame = frame.copy()
            height, width = processed_frame.shape[:2]

            if manual_rois and not trackers_initialized:
                for idx, bbox in enumerate(manual_rois):
                    x1, y1, x2, y2 = map(int, bbox)
                    x1 = max(0, min(x1, width - 1))
                    y1 = max(0, min(y1, height - 1))
                    x2 = max(0, min(x2, width))
                    y2 = max(0, min(y2, height))
                    if x2 <= x1 or y2 <= y1:
                        continue
                    tracker = _create_tracker()
                    tracker.init(frame, (x1, y1, x2 - x1, y2 - y1))
                    tracker_entries.append(
                        {
                            "tracker": tracker,
                            "id": f"manual_{idx}",
                        }
                    )
                trackers_initialized = True

            if enable_detection and sensitive_classes:
                try:
                    results = model(processed_frame, verbose=False)
                except TypeError:
                    results = model(processed_frame)
            else:
                results = []

            metadata: List[Dict[str, object]] = []
            detection_metadata: List[Dict[str, object]] = []

            manual_metadata: List[Dict[str, object]] = []
            active_trackers: List[Dict[str, object]] = []
            for entry in tracker_entries:
                tracker = entry["tracker"]
                ok, bbox = tracker.update(frame)
                if not ok:
                    continue
                x, y, w, h = bbox
                x1 = max(0, min(int(round(x)), width - 1))
                y1 = max(0, min(int(round(y)), height - 1))
                x2 = max(0, min(int(round(x + w)), width))
                y2 = max(0, min(int(round(y + h)), height))
                if x2 <= x1 or y2 <= y1:
                    continue

                roi = frame[y1:y2, x1:x2]
                encrypted_blob = encrypt_roi(roi, encryption_key)
                apply_obfuscation(processed_frame, (x1, y1, x2, y2), style_mode)

                block = {
                    "label": entry.get("id", "manual"),
                    "confidence": 1.0,
                    "bbox": (x1, y1, x2, y2),
                    "encrypted": encrypted_blob,
                    "source": "manual",
                }
                manual_metadata.append(block)
                _safe_callback(
                    status_callback,
                    "manual_roi",
                    {
                        "frame_index": frame_index,
                        "bbox": (x1, y1, x2, y2),
                        "tracker_id": entry.get("id", "manual"),
                    },
                )
                active_trackers.append(entry)

            tracker_entries = active_trackers

            # YOLOv8 returns a list; iterate over detections in the first result.
            for result in results:
                boxes = getattr(result, "boxes", None)
                if boxes is None:
                    continue

                names = getattr(result, "names", None)
                if names is None and hasattr(model, "model") and hasattr(model.model, "names"):
                    names = model.model.names

                for box in boxes:
                    cls_id = int(box.cls.item())
                    conf = float(box.conf.item())
                    if names:
                        label = names[cls_id]
                    else:
                        label = str(cls_id)

                    if label not in sensitive_classes:
                        continue

                    xyxy = box.xyxy.view(-1).tolist()
                    x1 = max(0, min(int(xyxy[0]), width - 1))
                    y1 = max(0, min(int(xyxy[1]), height - 1))
                    x2 = max(0, min(int(xyxy[2]), width))
                    y2 = max(0, min(int(xyxy[3]), height))
                    if x2 <= x1 or y2 <= y1:
                        continue

                    roi = frame[y1:y2, x1:x2]
                    encrypted_blob = encrypt_roi(roi, encryption_key)
                    apply_obfuscation(processed_frame, (x1, y1, x2, y2), style_mode)

                    block = {
                        "label": label,
                        "confidence": conf,
                        "bbox": (x1, y1, x2, y2),
                        "encrypted": encrypted_blob,
                        "source": "detection",
                    }
                    detection_metadata.append(block)
                    _safe_callback(
                        status_callback,
                        "detection",
                        {
                            "frame_index": frame_index,
                            "label": label,
                            "confidence": conf,
                            "bbox": (x1, y1, x2, y2),
                        },
                    )

            if manual_metadata:
                metadata.extend(manual_metadata)
            if detection_metadata:
                metadata.extend(detection_metadata)

            processed_queue.put((frame_index, processed_frame, metadata))
        finally:
            frame_queue.task_done()

    # signal consumer that processing is done
    processed_queue.put(sentinel)


def consumer(
    processed_queue: Queue,
    output_path: str,
    fps: float,
    frame_size: tuple[int, int],
    data_pack_writer: Optional[DataPackWriter] = None,
    sentinel: Optional[object] = None,
    status_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    total_frames: int = 0,
) -> None:
    """Write processed frames to an output video file until sentinel is received."""
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(output_path, fourcc, fps, frame_size)
    if not writer.isOpened():
        raise RuntimeError(f"无法创建输出视频: {output_path}")

    processed_count = 0

    try:
        while True:
            item = processed_queue.get()
            try:
                if item is sentinel:
                    break
                frame_index, processed_frame, metadata = item  # type: ignore[misc]
                if data_pack_writer is not None and metadata:
                    data_pack_writer.write_frame_data(frame_index, metadata)
                writer.write(processed_frame)
                processed_count += 1
                _safe_callback(
                    status_callback,
                    "progress",
                    {
                        "frame_index": frame_index,
                        "processed": processed_count,
                        "total_frames": total_frames,
                    },
                )
            finally:
                processed_queue.task_done()
    finally:
        writer.release()


def run_pipeline(
    video_path: str,
    output_path: str,
    model,
    encryption_key: bytes,
    data_pack_path: str,
    hmac_key: bytes,
    target_classes: Optional[Sequence[str]] = None,
    manual_rois: Optional[Sequence[Tuple[int, int, int, int]]] = None,
    status_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    style: str = "blur",
    enable_detection: bool = True,
) -> bytes:
    frame_queue: Queue = Queue(maxsize=32)
    processed_queue: Queue = Queue(maxsize=32)
    sentinel = object()
    num_workers = 1

    # Probe video metadata for the consumer
    tmp_cap = cv2.VideoCapture(video_path)
    if not tmp_cap.isOpened():
        raise RuntimeError(f"无法打开视频文件: {video_path}")
    fps = tmp_cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(tmp_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(tmp_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(tmp_cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    tmp_cap.release()

    _safe_callback(
        status_callback,
        "metadata",
        {
            "fps": fps,
            "width": width,
            "height": height,
            "total_frames": total_frames,
        },
    )

    output_path_obj = Path(output_path)
    output_path_obj.parent.mkdir(parents=True, exist_ok=True)
    data_pack_path_obj = Path(data_pack_path)
    data_pack_path_obj.parent.mkdir(parents=True, exist_ok=True)

    data_pack_writer = DataPackWriter(data_pack_path_obj, fps, width, height)

    producer_thread = threading.Thread(
        target=producer,
        args=(video_path, frame_queue, sentinel, num_workers),
        daemon=True,
    )
    worker_thread = threading.Thread(
        target=worker,
        args=(
            frame_queue,
            processed_queue,
            model,
            encryption_key,
            sentinel,
            target_classes,
            manual_rois,
            status_callback,
            style,
            enable_detection,
        ),
        daemon=True,
    )
    consumer_thread = threading.Thread(
        target=consumer,
        args=(
            processed_queue,
            str(output_path_obj),
            fps,
            (width, height),
            data_pack_writer,
            sentinel,
            status_callback,
            total_frames,
        ),
        daemon=True,
    )

    producer_thread.start()
    worker_thread.start()
    consumer_thread.start()

    producer_thread.join()
    frame_queue.join()
    processed_queue.join()
    worker_thread.join()
    consumer_thread.join()

    _safe_callback(status_callback, "finalizing", {})

    try:
        digest = data_pack_writer.finalize(hmac_key)
    finally:
        data_pack_writer.close()

    _safe_callback(status_callback, "finalized", {"digest": digest.hex()})

    return digest


if __name__ == "__main__":
    # Example usage with a no-op model (placeholder)
    class IdentityModel:
        def __call__(self, frame, *args, **kwargs):
            class Result:
                boxes = []

            return [Result()]

    dummy_model = IdentityModel()
    key = os.urandom(32)
    hmac_key = os.urandom(32)
    run_pipeline("input.mp4", "output.mp4", dummy_model, key, "encrypted_data.pack", hmac_key)
