"""API service entry point: python -m app.api"""
import uvicorn
from app.core import config_loader

if __name__ == "__main__":
    host = config_loader.get("api", "host", "0.0.0.0")
    port = config_loader.get("api", "port", 8000)
    uvicorn.run("app.api.main:app", host=host, port=port, reload=False)
