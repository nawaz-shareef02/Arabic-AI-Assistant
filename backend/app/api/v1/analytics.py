from fastapi import APIRouter

router = APIRouter(prefix="/analytics", tags=["ANALYTICS"])

@router.get("/")
async def read_analytics():
    return {"message": "Hello from analytics endpoint"}