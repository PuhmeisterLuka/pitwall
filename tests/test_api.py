import httpx
import pytest

from pitwall.api import create_app
from pitwall.errors import UpstreamBadResponse, UpstreamRateLimited

pytestmark = pytest.mark.anyio


@pytest.fixture
async def client(spa_sources):
    """Run the real app, lifespan included, in memory over the stubbed sources."""
    app = create_app(sources=spa_sources)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://pitwall.test") as client:
            yield client


async def test_health(client):
    assert (await client.get("/api/health")).json() == {"status": "ok"}


async def test_race_report(client):
    body = (await client.get("/api/seasons/2024/rounds/14")).json()
    event, winner = body["report"]["event"], body["report"]["entries"][0]

    assert (event["name"], event["starts_at"]) == ("Belgian Grand Prix", "2024-07-28T13:00:00Z")
    assert winner["driver"] == {
        "number": 44,
        "code": "HAM",
        "name": "Lewis Hamilton",
        "team": "Mercedes",
        "team_colour": "#27F4D2",
        "headshot_url": winner["driver"]["headshot_url"],
    }
    assert (winner["outcome"], winner["race_time_s"], winner["pit_stops"][0]["lap"]) == (
        "finished",
        4797.566,
        11,
    )
    assert body["sources"]["jolpica"]["status"] == "hit"


async def test_season_calendar(client):
    body = (await client.get("/api/seasons/2024")).json()
    assert [(e["round"], e["session_key"]) for e in body["events"]] == [(14, 9574)]


async def test_standings(client):
    body = (await client.get("/api/seasons/2024/rounds/14/standings")).json()
    assert body["standings"][0]["code"] == "VER"


async def test_missing_round_is_404(client):
    response = await client.get("/api/seasons/2024/rounds/15")
    assert response.status_code == 404
    assert response.json() == {"detail": "2024 has no round 15"}


async def test_throttled_upstream_is_503_with_retry_after(client, spa_sources):
    spa_sources.jolpica.answers["calendar"] = UpstreamRateLimited(
        "jolpica", "HTTP 429", retry_after=4.2
    )
    response = await client.get("/api/seasons/2024")

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "5"
    assert response.json() == {"detail": "HTTP 429", "source": "jolpica"}


async def test_unusable_upstream_answer_is_502(client, spa_sources):
    spa_sources.jolpica.answers["calendar"] = UpstreamBadResponse("jolpica", "invalid JSON")
    assert (await client.get("/api/seasons/2024")).status_code == 502


@pytest.mark.parametrize(
    "path", ["/api/seasons/1900", "/api/seasons/2024/rounds/0", "/api/seasons/abc"]
)
async def test_invalid_paths_are_422(client, path):
    assert (await client.get(path)).status_code == 422
