"""Route aggregation."""

from fastapi import APIRouter

from profsearch.web.routes.compare import router as compare_router
from profsearch.web.routes.email_draft import router as email_draft_router
from profsearch.web.routes.pipeline import router as pipeline_router
from profsearch.web.routes.professor import router as professor_router
from profsearch.web.routes.search import router as search_router

router = APIRouter()
router.include_router(search_router)
router.include_router(professor_router)
router.include_router(pipeline_router)
router.include_router(compare_router)
router.include_router(email_draft_router)
