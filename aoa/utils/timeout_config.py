"""Centralized timeout configuration to prevent Render proxy timeouts."""
import httpx

def get_render_safe_timeout():
    """Get an httpx timeout configuration safe for Render's 30-second proxy timeout."""
    from config import settings
    
    # Keep total request time under 25 seconds to avoid Render's 30-second proxy timeout
    return httpx.Timeout(
        connect=settings.external_api_connect_timeout,
        read=settings.external_api_timeout,
        write=settings.external_api_write_timeout,
        pool=5.0
    )

def get_quick_timeout():
    """Get a quick timeout for fast operations."""
    return httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=3.0)

def get_external_client():
    """Get an httpx.AsyncClient with Render-safe timeouts."""
    return httpx.AsyncClient(timeout=get_render_safe_timeout())

def get_quick_client():
    """Get an httpx.AsyncClient with quick timeouts for fast operations."""
    return httpx.AsyncClient(timeout=get_quick_timeout())
