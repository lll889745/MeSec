import os
import sys
import threading
from pathlib import Path
from queue import Queue
from typing import Dict, List, Optional, Sequence, Tuple

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


def anonymize_region(frame: np.ndarray, bbox: Tuple[int, int, int, int]) -> None:
    """Apply Gaussian blur to the specified bounding box region of the frame."""
    x1, y1, x2, y2 = bbox
    roi = frame[y1:y2, x1:x2]
    if roi.size == 0:
        return
    ksize = max(5, (min(roi.shape[0], roi.shape[1]) // 2) * 2 + 1)
    blurred = cv2.GaussianBlur(roi, (ksize, ksize), 0)
    frame[y1:y2, x1:x2] = blurred


def worker(
    frame_queue: Queue,
    processed_queue: Queue,
    model,
    encryption_key: bytes,
    sentinel: Optional[object] = None,
    target_classes: Optional[Sequence[str]] = None,
    manual_rois: Optional[Sequence[Tuple[int, int, int, int]]] = None,
) -> None:
    """Consume raw frames, run detection/anonymization, and enqueue results."""
    sensitive_classes = set(target_classes or ("person", "car", "truck", "bus", "motorcycle", "motorbike"))
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
                    tracker_entries.append({
                        "tracker": tracker,
                        "id": f"manual_{idx}",
                    })
                trackers_initialized = True

            try:
                results = model(processed_frame, verbose=False)
            except TypeError:
                results = model(processed_frame)
            metadata: List[Dict[str, object]] = []

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
                anonymize_region(processed_frame, (x1, y1, x2, y2))

                manual_metadata.append(
                    {
                        "label": entry.get("id", "manual"),
                        "confidence": 1.0,
                        "bbox": (x1, y1, x2, y2),
                        "encrypted": encrypted_blob,
                        "source": "manual",
                    }
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
                    anonymize_region(processed_frame, (x1, y1, x2, y2))

                    metadata.append(
                        {
                            "label": label,
                            "confidence": conf,
                            "bbox": (x1, y1, x2, y2),
                            "encrypted": encrypted_blob,
                        }
                    )

            if manual_metadata:
                metadata.extend(manual_metadata)

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
) -> None:
    """Write processed frames to an output video file until sentinel is received."""
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(output_path, fourcc, fps, frame_size)
    if not writer.isOpened():
        raise RuntimeError(f"无法创建输出视频: {output_path}")

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
    tmp_cap.release()

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
        args=(frame_queue, processed_queue, model, encryption_key, sentinel, target_classes, manual_rois),
        daemon=True,
    )
    consumer_thread = threading.Thread(
        target=consumer,
    args=(processed_queue, str(output_path_obj), fps, (width, height), data_pack_writer, sentinel),
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

    try:
        digest = data_pack_writer.finalize(hmac_key)
    finally:
        data_pack_writer.close()
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
