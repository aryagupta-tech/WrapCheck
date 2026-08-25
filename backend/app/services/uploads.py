import re
from pathlib import Path

from fastapi import HTTPException, UploadFile

ALLOWED_TYPES = {
    "video/mp4", "video/quicktime", "application/pdf", "text/plain",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


def sanitized_filename(name: str | None) -> str:
    cleaned = SAFE_FILENAME.sub("-", Path(name or "upload").name).strip(".-")
    return cleaned[:160] or "upload"


async def validate_upload(file: UploadFile, max_mb: int) -> dict:
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported file type")
    content = await file.read(max_mb * 1024 * 1024 + 1)
    if len(content) > max_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File exceeds {max_mb} MB limit")
    return {"filename": sanitized_filename(file.filename), "content_type": file.content_type, "size": len(content)}
