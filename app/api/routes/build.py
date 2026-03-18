"""Build routes — thin wrapper over daemon IPC.

File upload: API saves to a temp path, sends the path to the daemon.
The daemon moves the file into datasets/{id}/.
"""
import os
import tempfile

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form

from app.auth.dependencies import get_current_user
from app.api.ipc_client import get_client, IpcError

router = APIRouter(tags=["build"])


def _ctx(user: dict) -> dict:
    return {"source": "api", "user_id": user["id"], "role": user["role"]}


async def _call(method, params, context):
    try:
        return await get_client().call(method, params, context)
    except IpcError as e:
        raise HTTPException(status_code=e.code, detail=e.message)


@router.post("/build/submit")
async def build_submit(
    file: UploadFile = File(...),
    name: str = Form(...),
    algorithm: str = Form("flat"),
    nlist: int = Form(None),
    pq_m: int = Form(None),
    nbits: int = Form(None),
    hnsw_m: int = Form(None),
    ef_construction: int = Form(None),
    user: dict = Depends(get_current_user),
):
    # Save upload to a temp file; daemon will move it
    suffix = os.path.splitext(file.filename or "input.fasta")[1] or ".fasta"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        content = await file.read()
        tmp.write(content)
        tmp.flush()
        tmp.close()

        params = {
            "fasta_tmp_path": tmp.name,
            "name": name,
            "algorithm": algorithm,
        }
        for k, v in [("nlist", nlist), ("pq_m", pq_m), ("nbits", nbits),
                     ("hnsw_m", hnsw_m), ("ef_construction", ef_construction)]:
            if v is not None:
                params[k] = v

        return await _call("build.submit", params, _ctx(user))
    except Exception:
        # Clean up temp file on error (daemon cleans up on success)
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        raise


@router.get("/build/status/{dataset_id}")
async def build_status(dataset_id: str, user: dict = Depends(get_current_user)):
    return await _call("build.status", {"dataset_id": dataset_id}, _ctx(user))
