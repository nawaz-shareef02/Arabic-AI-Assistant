from fastapi import APIRouter

router = APIRouter(prefix="/users", tags=["USERS"])

@router.get("/")
async def read_users():
    return {"message": "Hello from users endpoint"}