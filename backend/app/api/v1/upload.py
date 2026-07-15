from fastapi import APIRouter

router = APIRouter(prefix="/upload", tags=["UPLOAD"])

@router.get("/")
async def read_upload():
    return {"message": "Hello from upload endpoint"}