"""Export / import HTTP routes — thin wrappers over daemon IPC."""
import os
import tempfile

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse

from app.auth.dependencies import get_current_user
from app.api.ipc_client import get_client, IpcError

router = APIRouter(tags=["export-import"])


def _ctx(user: dict) -> dict:
    return {"source": "api", "user_id": user["id"], "role": user["role"]}


async def _call(method, params, context):
    try:
        return await get_client().call(method, params, context)
    except IpcError as e:
        raise HTTPException(status_code=e.code, detail=e.message)


# ---------------------------------------------------------------------------
# Export endpoints
# ---------------------------------------------------------------------------

@router.post("/datasets/{dataset_id}/export")
async def export_dataset(
    dataset_id: str,
    user: dict = Depends(get_current_user),
):
    return await _call("dataset.export", {"dataset_id": dataset_id}, _ctx(user))


@router.get("/datasets/{dataset_id}/export/status")
async def export_status(
    dataset_id: str,
    user: dict = Depends(get_current_user),
):
    return await _call("dataset.export_status", {"dataset_id": dataset_id}, _ctx(user))


@router.get("/datasets/{dataset_id}/export/download")
async def export_download(
    dataset_id: str,
    user: dict = Depends(get_current_user),
):
    status = await _call("dataset.export_status", {"dataset_id": dataset_id}, _ctx(user))

    if status.get("status") != "done":
        raise HTTPException(
            status_code=404,
            detail=f"Export not ready (status: {status.get('status')})",
        )

    export_path = status.get("export_path")
    if not export_path or not os.path.isfile(export_path):
        raise HTTPException(status_code=404, detail="Export file not found on disk")

    dataset_name = status.get("dataset_name", "export")
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in dataset_name)
    filename = f"{safe_name}.7z"

    # Use FileResponse for efficient OS-level sendfile
    return FileResponse(
        path=export_path,
        media_type="application/x-7z-compressed",
        filename=filename,
    )


# ---------------------------------------------------------------------------
# Import endpoint
# ---------------------------------------------------------------------------

@router.post("/datasets/import")
async def import_dataset(
    file: UploadFile = File(...),
    name: str = Form(""),
    user: dict = Depends(get_current_user),
):
    """Accept a .7z archive upload and start an import job."""
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".7z")
    try:
        content = await file.read()
        tmp.write(content)
        tmp.flush()
        tmp.close()

        return await _call(
            "dataset.import",
            {"archive_tmp_path": tmp.name, "name": name},
            _ctx(user),
        )
    except Exception:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        raise


@router.get("/datasets/import/{dataset_id}/status")
async def import_status(
    dataset_id: str,
    user: dict = Depends(get_current_user),
):
    """Poll the status of an in-progress import (reuses build.status)."""
    return await _call("build.status", {"dataset_id": dataset_id}, _ctx(user))
