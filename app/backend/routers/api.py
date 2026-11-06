from fastapi import APIRouter

from routers.benchmark import router as benchmark_router
from routers.download import router as download_router
from routers.health import router as health_router
from routers.history import router as history_router
from routers.process import router as process_router
from routers.queue import router as queue_router
from routers.result import router as result_router
from routers.result_download import router as result_download_router
from routers.result_stages import router as result_stages_router
from routers.settings import router as settings_router
from routers.stt_models import router as stt_models_router

router = APIRouter(prefix="/api")
router.include_router(process_router)
router.include_router(stt_models_router)     # (between process and queue, where these endpoints always were)
router.include_router(queue_router)     # (the queue endpoints used to be the end of process.py: same place in the order)
router.include_router(result_router)
router.include_router(result_stages_router)
router.include_router(result_download_router)
router.include_router(history_router)
router.include_router(download_router)
router.include_router(settings_router)
router.include_router(health_router)
router.include_router(benchmark_router)
