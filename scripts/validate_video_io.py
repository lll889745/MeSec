import argparse
import cv2
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate video IO by copying frames to a new file.")
    parser.add_argument("input_video", type=Path, help="Path to the input video file")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = args.input_video

    if not input_path.exists():
        print(f"输入视频不存在: {input_path}", file=sys.stderr)
        sys.exit(1)

    cap = cv2.VideoCapture(str(input_path))
    if not cap.isOpened():
        print(f"无法打开视频: {input_path}", file=sys.stderr)
        sys.exit(1)

    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    print(f"视频信息 -> 帧率: {fps:.2f}, 分辨率: {width}x{height}")

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out_path = input_path.parent / "output.mp4"
    writer = cv2.VideoWriter(str(out_path), fourcc, fps, (width, height))

    if not writer.isOpened():
        print(f"无法创建输出视频: {out_path}", file=sys.stderr)
        cap.release()
        sys.exit(1)

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            writer.write(frame)
    finally:
        cap.release()
        writer.release()

    print("视频复制完成")


def entry_point() -> None:
    main()


if __name__ == "__main__":
    entry_point()
