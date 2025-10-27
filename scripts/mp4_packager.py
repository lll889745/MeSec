from __future__ import annotations

import os
import shutil
import struct
import uuid
from pathlib import Path
from typing import Optional

# 固定 UUID，匹配我们自定义的 ROI 数据附加盒。
DEFAULT_PACK_UUID = uuid.UUID("1f0cf7d5-1c3c-4e25-ba9d-5cb0fc61f847")


def _build_uuid_box(payload: bytes, box_uuid: uuid.UUID) -> bytes:
    """Construct a UUID box (size | 'uuid' | uuid | payload)."""
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise TypeError("payload must be bytes-like")

    payload_bytes = bytes(payload)
    box_size = 4 + 4 + 16 + len(payload_bytes)
    if box_size >= 2 ** 32:
        raise ValueError("payload too large for a standard ISO box")

    header = struct.pack(
        ">I4s16s",
        box_size,
        b"uuid",
        box_uuid.bytes,
    )
    return header + payload_bytes


def embed_pack_into_mp4(
    video_path: Path | str,
    pack_path: Path | str,
    output_path: Optional[Path | str] = None,
    *,
    box_uuid: uuid.UUID = DEFAULT_PACK_UUID,
) -> Path:
    """Append the `.pack` contents into an MP4 as a custom UUID box."""
    video_path = Path(video_path)
    pack_path = Path(pack_path)

    if not video_path.is_file():
        raise FileNotFoundError(f"video file not found: {video_path}")
    if not pack_path.is_file():
        raise FileNotFoundError(f"data pack not found: {pack_path}")

    payload = pack_path.read_bytes()
    uuid_box = _build_uuid_box(payload, box_uuid)

    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(video_path, output_path)
        target_path = output_path
    else:
        target_path = video_path

    with target_path.open("ab") as stream:
        stream.write(uuid_box)

    return target_path


def extract_pack_from_mp4(
    video_path: Path | str,
    *,
    box_uuid: uuid.UUID = DEFAULT_PACK_UUID,
) -> bytes:
    """Locate and return the bytes payload stored in our UUID box."""
    video_path = Path(video_path)
    if not video_path.is_file():
        raise FileNotFoundError(f"video file not found: {video_path}")

    uuid_bytes = box_uuid.bytes
    file_size = video_path.stat().st_size

    with video_path.open("rb") as stream:
        offset = 0
        while offset < file_size:
            header = stream.read(8)
            if len(header) < 8:
                break

            size, box_type = struct.unpack(">I4s", header)
            offset += 8

            if size == 1:
                largesize_bytes = stream.read(8)
                if len(largesize_bytes) < 8:
                    break
                size = struct.unpack(">Q", largesize_bytes)[0]
                header_size = 16
                offset += 8
            else:
                header_size = 8

            if size == 0:
                size = file_size - offset + header_size

            if size < header_size:
                raise ValueError("invalid MP4 box size encountered")

            payload_size = size - header_size

            if box_type == b"uuid":
                uuid_field = stream.read(16)
                if len(uuid_field) < 16:
                    break
                offset += 16
                payload_size -= 16
                if payload_size < 0:
                    raise ValueError("invalid UUID box length")
                if uuid_field == uuid_bytes:
                    payload = stream.read(payload_size)
                    if len(payload) != payload_size:
                        raise ValueError("unexpected EOF when reading UUID payload")
                    return payload
                stream.seek(payload_size, os.SEEK_CUR)
                offset += payload_size
            else:
                stream.seek(payload_size, os.SEEK_CUR)
                offset += payload_size

    raise FileNotFoundError("embedded pack not found in MP4")


def extract_pack_to_file(
    video_path: Path | str,
    output_path: Path | str,
    *,
    box_uuid: uuid.UUID = DEFAULT_PACK_UUID,
) -> Path:
    """Extract the embedded payload and persist it as a `.pack` file."""
    payload = extract_pack_from_mp4(video_path, box_uuid=box_uuid)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(payload)
    return output_path
