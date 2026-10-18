"""Run the server: python -m server"""
import uvicorn

from core.config import get_settings

from .app import create_app

if __name__ == "__main__":
    settings = get_settings()
    # proxy_headers off: the app reads X-Forwarded-For itself, only when TRUST_PROXY is set
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, proxy_headers=False,
                server_header=False, log_config=None, ws_max_size=64_000, timeout_keep_alive=10)
