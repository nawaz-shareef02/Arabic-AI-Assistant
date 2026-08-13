"""
Upload API Router — Reserved Future Endpoint.

Note: Document ingestion uploads are actively handled via POST /api/v1/documents/upload.
This top-level /upload router is reserved for standalone bulk file streaming APIs in future sprints.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/upload", tags=["UPLOAD"])


@router.get("/", summary="Upload service status (Future Reserved)")
async def read_upload():
    return {
        "status": "reserved",
        "message": "Standalone bulk upload route reserved. Use POST /api/v1/documents/upload for document ingestion.",
    }