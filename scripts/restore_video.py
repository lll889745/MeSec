import argparse
import sys
from pathlib import Path
from typing import Dict, List, Tuple

CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import cv2
import numpy as np
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from scripts.data_pack import DataPackReader


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Restore anonymized video using encrypted ROI data.")
    parser.add_argument(
        "--anonymized-video",
        type=Path,
        required=True,
        help="Path to the anonymized video file",
    )
    parser.add_argument(
        "--data-pack",
        type=Path,
        required=True,
        help="Path to the encrypted ROI data pack",
    )
    parser.add_argument(
        "--key",
        type=str,
        required=True,
        help="Hex-encoded AES key used for ROI decryption",
    )
    parser.add_argument(
        "--hmac-key",
        type=str,
        default=None,
        help="Hex-encoded HMAC key used for pack integrity (defaults to AES key)",
    )
    return parser.parse_args()


def decode_key(key_hex: str) -> bytes:
    try:
        key = bytes.fromhex(key_hex)
    except ValueError as exc:  # pragma: no cover - invalid user input path
        raise ValueError("密钥必须是合法的十六进制字符串") from exc

    if len(key) not in (16, 24, 32):
        raise ValueError("仅支持 128/192/256 位的 AES 密钥 (16/24/32 字节)")
    return key


def decrypt_roi(payload: bytes, key: bytes, width: int, height: int) -> np.ndarray:
    if len(payload) < 12 + 16:
        raise ValueError("加密数据包格式不正确，长度不足")

    nonce = payload[:12]
    tag = payload[-16:]
    ciphertext = payload[12:-16]

    decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
    try:
        plaintext = decryptor.update(ciphertext) + decryptor.finalize()
    except InvalidTag as exc:
        raise InvalidTag("ROI 解密失败，认证标签无效") from exc

    expected_length = height * width * 3
    if len(plaintext) != expected_length:
        raise ValueError("解密后的 ROI 长度与坐标尺寸不一致")

    array = np.frombuffer(plaintext, dtype=np.uint8)
    return array.reshape((height, width, 3))


def load_data_pack(data_pack: Path, hmac_key: bytes) -> Tuple[Dict[int, List[dict]], float, Tuple[int, int]]:
    with DataPackReader(data_pack) as reader:
        if not reader.verify(hmac_key):
            raise RuntimeError("数据包 HMAC 校验失败，文件可能被篡改")

        frame_map: Dict[int, List[dict]] = {}
        for frame_index, blocks in reader.iter_frames():
            frame_map[frame_index] = blocks

        fps = reader.framerate
        frame_size = (reader.width, reader.height)

    return frame_map, fps, frame_size


def main() -> None:
    args = parse_args()
    key = decode_key(args.key)
    hmac_key = decode_key(args.hmac_key) if args.hmac_key else key

    frame_map, pack_fps, pack_size = load_data_pack(args.data_pack, hmac_key)

    cap = cv2.VideoCapture(str(args.anonymized_video))
    if not cap.isOpened():
        raise RuntimeError(f"无法打开匿名视频: {args.anonymized_video}")

    video_fps = cap.get(cv2.CAP_PROP_FPS) or pack_fps or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if width == 0 or height == 0:
        if pack_size[0] <= 0 or pack_size[1] <= 0:
            cap.release()
            raise RuntimeError("无法获取视频分辨率")
        width, height = pack_size

    if pack_size != (0, 0) and pack_size != (width, height):
        print("警告：数据包记录的分辨率与视频实际尺寸不一致，将以视频尺寸为准。")

    output_path = args.anonymized_video.with_name("restored_video.mp4")
    writer = cv2.VideoWriter(
        str(output_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        float(video_fps),
        (width, height),
    )
    if not writer.isOpened():
        cap.release()
        raise RuntimeError(f"无法创建输出视频: {output_path}")

    frame_index = 0
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            blocks = frame_map.get(frame_index, [])
            for block in blocks:
                bbox = block.get("bbox")
                encrypted = block.get("encrypted", b"")
                if bbox is None:
                    continue

                x1, y1, x2, y2 = map(int, bbox)
                x1 = max(0, min(x1, width - 1))
                y1 = max(0, min(y1, height - 1))
                x2 = max(0, min(x2, width))
                y2 = max(0, min(y2, height))

                roi_width = max(0, x2 - x1)
                roi_height = max(0, y2 - y1)
                if roi_width == 0 or roi_height == 0:
                    continue

                restored_roi = decrypt_roi(encrypted, key, roi_width, roi_height)
                frame[y1:y2, x1:x2] = restored_roi

            writer.write(frame)
            frame_index += 1
    finally:
        cap.release()
        writer.release()

    print(f"恢复完成，输出文件: {output_path}")


if __name__ == "__main__":
    main()
