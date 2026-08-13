"""
Models API Router — Reserved Future Endpoint.

This module is a placeholder for LLM model selection, runtime parameter
tuning, and Ollama model switching scheduled for future sprints.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/models", tags=["MODELS"])


@router.get("/", summary="Models registry status (Future Reserved)")
async def read_models():
    return {
        "status": "reserved",
        "message": "Models management API is reserved for future dynamic provider releases.",
    }