"""HTTP API: three read-only views and a health check. Run with `uvicorn pitwall.api:app`."""

import math
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, nullcontext
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Path, Request
from fastapi.responses import JSONResponse

from pitwall.config import Settings
from pitwall.errors import UpstreamError
from pitwall.service import NotFound, RaceService, RaceView, SeasonView, StandingsView
from pitwall.sources import Sources, open_sources

Season = Annotated[int, Path(ge=1950, le=2100)]
Round = Annotated[int, Path(ge=1, le=30)]


def get_service(request: Request) -> RaceService:
    return request.app.state.service


Service = Annotated[RaceService, Depends(get_service)]
router = APIRouter(prefix="/api")


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/seasons/{season}")
async def season(season: Season, service: Service) -> SeasonView:
    return await service.season(season)


@router.get("/seasons/{season}/rounds/{round_no}")
async def race(season: Season, round_no: Round, service: Service) -> RaceView:
    return await service.race(season, round_no)


@router.get("/seasons/{season}/rounds/{round_no}/standings")
async def standings(season: Season, round_no: Round, service: Service) -> StandingsView:
    return await service.standings(season, round_no)


def upstream_failed(request: Request, error: UpstreamError) -> JSONResponse:
    """503 when retrying later can help (outage, throttling), 502 for unusable answers."""
    headers = {"Retry-After": str(math.ceil(error.retry_after))} if error.retry_after else None
    return JSONResponse(
        {"detail": error.message, "source": error.source},
        status_code=503 if error.retryable else 502,
        headers=headers,
    )


def not_found(request: Request, error: NotFound) -> JSONResponse:
    return JSONResponse({"detail": str(error)}, status_code=404)


def create_app(settings: Settings | None = None, *, sources: Sources | None = None) -> FastAPI:
    """Build the app. Tests pass `sources` so nothing calls the real APIs."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if sources is not None:
            opened = nullcontext(sources)
        else:
            opened = open_sources(settings or Settings.from_env())
        async with opened as ready:
            app.state.service = RaceService(ready)
            yield

    app = FastAPI(
        title="pitwall",
        summary="Jolpica-F1 and OpenF1 race data, merged, cached and normalized.",
        lifespan=lifespan,
    )
    app.include_router(router)
    app.add_exception_handler(UpstreamError, upstream_failed)
    app.add_exception_handler(NotFound, not_found)
    return app


app = create_app()
