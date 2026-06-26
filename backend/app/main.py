from fastapi import FastAPI

app = FastAPI(
    title="Arabic-English AI Assistant",
    version="1.0.0"
)

@app.get("/")
def root():
    return {
        "message": "Arabic-English AI Assistant Backend Running 🚀"
    }
