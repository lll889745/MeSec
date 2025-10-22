"""Placeholder backend service for reversible video anonymization pipeline.

This module will host the core Python services that interface with CUDA-accelerated
PyTorch models (YOLOv8) and OpenCV transforms. It is currently a minimal FastAPI
application exposing a health check endpoint so that the Electron frontend can
verify that the Python runtime is available.
"""
from fastapi import FastAPI

app = FastAPI(title="Reversible Video Anonymizer Backend")


@app.get("/health")
def get_health() -> dict[str, str]:
    """Return a static message until real diagnostics are available."""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
