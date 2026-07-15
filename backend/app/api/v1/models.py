from fastapi import APIRouter

router = APIRouter(prefix="/models", tags=["MODELS"])

@router.get("/")
async def read_models():
    return {"message": "Hello from models endpoint"}