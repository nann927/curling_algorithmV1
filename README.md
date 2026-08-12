# Curling Smart Director Algorithm Service

Phase 0-2 skeleton for the curling smart director algorithm service.

## Run

```bash
python -m venv .venv
pip install -r requirements.txt
python run.py
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

Generate local Phase 3 test videos:

```bash
python scripts/generate_test_videos.py
```

Run Integration/Mock flow:

```bash
APP_ENV=integration MOCK_MODE=true PUBLIC_BASE_URL=http://localhost:8000 python run.py
python scripts/integration_flow.py
```

## Current Scope

- FastAPI API skeleton.
- In-process RuntimeManager with match-level and sheet-level state.
- Mock smart director and overview live outputs.
- Mock post-processing and software upload.
- SQLite initialization skeleton.
- Config-driven site device mapping through `config/site_config.json`.
- Local MP4 video source provider and FFmpeg process lifecycle management for Phase 3 local verification.

## Not Implemented Yet

RTSP, microphone capture, FFmpeg realtime muxing, electronic curling WebSocket/TCP, real camera switching, OpenCV analysis, ThrowerRecognizer real calls, clipping/concatenation, and real software uploads are intentionally not implemented in this phase.
