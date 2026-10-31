from fastapi import APIRouter

from routers.benchmark import router as benchmark_router
from routers.download import router as download_router
from routers.health import router as health_router
from routers.history import router as history_router
from routers.process import router as process_router
from routers.result import router as result_router
from routers.settings import router as settings_router

router = APIRouter(prefix="/api")
router.include_router(process_router)
router.include_router(result_router)
router.include_router(history_router)
router.include_router(download_router)
router.include_router(settings_router)
router.include_router(health_router)
router.include_router(benchmark_router)
