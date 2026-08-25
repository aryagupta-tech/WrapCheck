from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile

from app.services.uploads import sanitized_filename, validate_upload


def test_filename_is_sanitized():
    assert sanitized_filename("../../scene 24?.mp4") == "scene-24-.mp4"


@pytest.mark.asyncio
async def test_upload_type_is_validated():
    upload = UploadFile(filename="payload.exe", file=BytesIO(b"no"), headers={"content-type": "application/octet-stream"})
    with pytest.raises(HTTPException) as error:
        await validate_upload(upload, 1)
    assert error.value.status_code == 415
