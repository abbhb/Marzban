from fastapi import APIRouter
from . import (
    admin, 
    commerce,
    core, 
    mgma,
    node, 
    subscription, 
    system, 
    user_template, 
    user,
    home,
)

api_router = APIRouter()

routers = [
    # Exact MGMA public paths must be registered before the legacy
    # ``/{token}`` subscription catch-all.
    commerce.router,
    mgma.router,
    admin.router,
    core.router,
    node.router,
    subscription.router,
    system.router,
    user_template.router,
    user.router,
    home.router,
]

for router in routers:
    api_router.include_router(router)

__all__ = ["api_router"]
