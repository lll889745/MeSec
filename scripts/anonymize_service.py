import json
import sys
import threading
import traceback
from concurrent.futures import CancelledError
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ultralytics import YOLO  # noqa: E402

from scripts.anonymize_video import (  # noqa: E402
    AnonymizationRequest,
    resolve_device,
    run_anonymization,
)


@dataclass
class JobState:
    thread: threading.Thread
    cancel_event: threading.Event


_stdout_lock = threading.Lock()


def _emit(payload: Dict[str, Any]) -> None:
    with _stdout_lock:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def _emit_event(job_id: str, event: str, data: Optional[Dict[str, Any]] = None) -> None:
    payload: Dict[str, Any] = {"jobId": job_id, "event": event}
    if data:
        payload.update(data)
    _emit(payload)


def _to_roi_list(manual_rois: Optional[Sequence[Sequence[int]]]) -> Optional[Sequence[Tuple[int, int, int, int]]]:
    if not manual_rois:
        return None
    normalized = []
    for roi in manual_rois:
        if len(roi) != 4:
            raise ValueError("manualRois entry must contain four coordinates")
        x1, y1, x2, y2 = (int(value) for value in roi)
        normalized.append((x1, y1, x2, y2))
    return normalized


class AnonymizeService:
    def __init__(self) -> None:
        self._model: Optional[YOLO] = None
        self._model_key: Optional[Tuple[str, str]] = None
        self._jobs: Dict[str, JobState] = {}
        self._service_lock = threading.Lock()

    def _ensure_model(self, model_path: Path, device: str) -> YOLO:
        key = (str(model_path), device)
        if self._model is not None and self._model_key == key:
            return self._model

        model = YOLO(str(model_path))
        model.to(device)
        self._model = model
        self._model_key = key
        return model

    def start_job(self, command: Dict[str, Any]) -> None:
        job_id = str(command.get("jobId"))
        payload = command.get("payload", {})
        if not job_id or not payload:
            _emit_event(job_id or "unknown", "error", {"message": "Missing jobId or payload"})
            _emit_event(job_id or "unknown", "exit", {"code": 1})
            return

        with self._service_lock:
            for existing in list(self._jobs.values()):
                if existing.thread.is_alive():
                    _emit_event(job_id, "error", {"message": "Another anonymization job is still running"})
                    _emit_event(job_id, "exit", {"code": 1})
                    return

        try:
            model_path = Path(payload.get("modelPath") or "yolov8n.pt")
            device = str(payload.get("device", "auto"))
            resolved_device = resolve_device(device)
            model = self._ensure_model(model_path, resolved_device)
            manual_rois = _to_roi_list(payload.get("manualRois"))

            request = AnonymizationRequest(
                input_path=Path(payload["inputPath"]),
                output_path=Path(payload["outputPath"]),
                data_pack_path=Path(payload["dataPackPath"]),
                device=resolved_device,
                classes=payload.get("classes"),
                manual_rois=manual_rois,
                aes_key_hex=payload.get("aesKey"),
                hmac_key_hex=payload.get("hmacKey"),
                style=payload.get("style", "blur"),
                disable_detector=bool(payload.get("disableDetection", False)),
                worker_count=max(1, int(payload.get("workerCount", 1))),
                embed_pack=bool(payload.get("embedPack", False)),
                embedded_output_path=Path(payload["embeddedOutputPath"]) if payload.get("embeddedOutputPath") else None,
            )
        except Exception as exc:
            _emit_event(job_id, "error", {"message": str(exc)})
            _emit_event(job_id, "exit", {"code": 1})
            return

        cancel_event = threading.Event()

        def logger(message: str) -> None:
            _emit_event(job_id, "log", {"message": message})

        def status_callback(event: str, data: Dict[str, Any]) -> None:
            _emit_event(job_id, event, data)
            if cancel_event.is_set():
                raise CancelledError()

        def runner() -> None:
            exit_code = 0
            try:
                _emit_event(
                    job_id,
                    "started",
                    {
                        "input": str(request.input_path),
                        "output": str(request.output_path),
                        "data_pack": str(request.data_pack_path),
                        "embed_pack": request.embed_pack,
                    },
                )
                if request.embedded_output_path is not None:
                    _emit_event(
                        job_id,
                        "embedded_output_resolved",
                        {"path": str(request.embedded_output_path)},
                    )
                result = run_anonymization(
                    model,
                    request,
                    status_callback=status_callback,
                    cancel_event=cancel_event,
                    logger=logger,
                )
                digest_bytes = result["digest"]
                aes_key = result["aes_key"]
                hmac_key = result["hmac_key"]
                embedded_output = result.get("embedded_output")
                completed_payload = {
                    "output": result["output"],
                    "data_pack": result["data_pack"],
                    "digest": digest_bytes.hex(),
                    "aes_key": aes_key.hex(),
                    "hmac_key": hmac_key.hex(),
                }
                if embedded_output:
                    completed_payload["embedded_output"] = embedded_output
                _emit_event(job_id, "completed", completed_payload)
            except CancelledError:
                exit_code = 0
                _emit_event(job_id, "cancelled")
            except Exception as exc:
                exit_code = 1
                _emit_event(
                    job_id,
                    "error",
                    {"message": str(exc), "traceback": traceback.format_exc()},
                )
            finally:
                _emit_event(job_id, "exit", {"code": exit_code})
                with self._service_lock:
                    self._jobs.pop(job_id, None)

        thread = threading.Thread(target=runner, name=f"anonymize-job-{job_id}", daemon=True)
        with self._service_lock:
            self._jobs[job_id] = JobState(thread=thread, cancel_event=cancel_event)
        thread.start()

    def cancel_job(self, job_id: str) -> None:
        with self._service_lock:
            state = self._jobs.get(job_id)
            if not state:
                _emit_event(job_id, "error", {"message": "Job not found"})
                _emit_event(job_id, "exit", {"code": 1})
                return
            state.cancel_event.set()

    def shutdown(self) -> None:
        with self._service_lock:
            for job_id, state in list(self._jobs.items()):
                state.cancel_event.set()
            jobs = list(self._jobs.values())
        for state in jobs:
            state.thread.join()


def main() -> None:
    service = AnonymizeService()
    for line in sys.stdin:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            command = json.loads(stripped)
        except json.JSONDecodeError:
            _emit({"event": "service_error", "message": "Invalid JSON command"})
            continue

        command_type = command.get("type")
        if command_type == "start":
            service.start_job(command)
        elif command_type == "cancel":
            job_id = str(command.get("jobId"))
            service.cancel_job(job_id)
        elif command_type == "shutdown":
            service.shutdown()
            break
        else:
            _emit({"event": "service_error", "message": f"Unknown command type: {command_type}"})


if __name__ == "__main__":
    main()
