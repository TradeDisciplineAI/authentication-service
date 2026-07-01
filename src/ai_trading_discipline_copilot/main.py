from fastapi import FastAPI

app = FastAPI(
    title="AI Trading Discipline Copilot",
    version="0.1.0",
    description="Minimal setup to test the Docker build",
)


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "Hello from AI Trading Discipline Copilot!"}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.1.0", "env": "development"}
