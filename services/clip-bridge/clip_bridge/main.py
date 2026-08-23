import hmac
import os
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status

from .models import (
    AnalysisRunClaim,
    AnalysisRunUpdate,
    CandidateCreate,
    CandidateReview,
    VideoStatusUpdate,
)
from .storage import Storage


SERVICE_TOKEN = os.environ.get("PEERTUBE_CLIPPER_SERVICE_TOKEN", "")
DATABASE = os.environ.get("PEERTUBE_CLIPPER_DATABASE", "./peertube-clipper.sqlite3")

app = FastAPI(
    title="PeerTube Clipper Bridge",
    version="0.1.0-alpha.1",
    docs_url=None,
    redoc_url=None,
)

storage = Storage(DATABASE)


def require_service_token(
    x_peertube_clipper_token: str | None = Header(default=None),
) -> None:
    if not SERVICE_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="service token is not configured",
        )

    if not x_peertube_clipper_token or not hmac.compare_digest(
        x_peertube_clipper_token,
        SERVICE_TOKEN,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid service credential",
        )


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "service": "peertube-clipper-bridge"}


@app.get("/v1/videos", dependencies=[Depends(require_service_token)])
def list_videos(status_filter: list[str] = Query(default=[], alias="status")) -> list[dict]:
    return storage.list_videos(status_filter or None)


@app.put("/v1/videos/{video_uuid}", dependencies=[Depends(require_service_token)])
def ensure_video(video_uuid: UUID) -> dict:
    return storage.ensure_video(video_uuid)


@app.patch(
    "/v1/videos/{video_uuid}/status",
    dependencies=[Depends(require_service_token)],
)
def update_video_status(video_uuid: UUID, update: VideoStatusUpdate) -> dict:
    return storage.set_video_status(video_uuid, update.status)


@app.get("/v1/videos/{video_uuid}", dependencies=[Depends(require_service_token)])
def get_video(video_uuid: UUID) -> dict:
    state = storage.get_video(video_uuid)
    if not state:
        raise HTTPException(status_code=404, detail="video workflow not found")

    return {
        "video": state,
        "candidates": storage.list_candidates(video_uuid),
        "analysis_runs": storage.list_analysis_runs(video_uuid),
    }


@app.delete("/v1/videos/{video_uuid}", dependencies=[Depends(require_service_token)])
def delete_video(video_uuid: UUID) -> dict:
    if not storage.delete_video(video_uuid):
        raise HTTPException(status_code=404, detail="video workflow not found")

    return {"deleted": True, "video_uuid": str(video_uuid)}


@app.get(
    "/v1/videos/{video_uuid}/candidates",
    dependencies=[Depends(require_service_token)],
)
def list_candidates(video_uuid: UUID) -> list[dict]:
    return storage.list_candidates(video_uuid)


@app.post(
    "/v1/videos/{video_uuid}/candidates",
    dependencies=[Depends(require_service_token)],
)
def create_candidate(video_uuid: UUID, candidate: CandidateCreate) -> dict:
    try:
        return storage.create_candidate(video_uuid, candidate)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.patch(
    "/v1/videos/{video_uuid}/candidates/{candidate_id}",
    dependencies=[Depends(require_service_token)],
)
def review_candidate(
    video_uuid: UUID,
    candidate_id: str,
    review: CandidateReview,
) -> dict:
    try:
        result = storage.review_candidate(video_uuid, candidate_id, review)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if not result:
        raise HTTPException(status_code=404, detail="candidate not found")

    return result


@app.get(
    "/v1/videos/{video_uuid}/analysis-runs",
    dependencies=[Depends(require_service_token)],
)
def list_analysis_runs(video_uuid: UUID) -> list[dict]:
    return storage.list_analysis_runs(video_uuid)


@app.post(
    "/v1/videos/{video_uuid}/analysis-runs/claim",
    dependencies=[Depends(require_service_token)],
)
def claim_analysis_run(video_uuid: UUID, claim: AnalysisRunClaim) -> dict:
    run, created = storage.claim_analysis_run(video_uuid, claim)
    return {"created": created, "analysis_run": run}


@app.patch(
    "/v1/videos/{video_uuid}/analysis-runs/{analysis_run_id}",
    dependencies=[Depends(require_service_token)],
)
def update_analysis_run(
    video_uuid: UUID,
    analysis_run_id: str,
    update: AnalysisRunUpdate,
) -> dict:
    run = storage.update_analysis_run(video_uuid, analysis_run_id, update)
    if not run:
        raise HTTPException(status_code=404, detail="analysis run not found")
    return run
