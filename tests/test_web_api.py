import os
import asyncio
import pytest
from httpx import ASGITransport, AsyncClient


def _run(coro):
    return asyncio.run(coro)


def test_health():
    from web import api
    async def _test():
        transport = ASGITransport(app=api.app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            return await ac.get("/health")
    resp = _run(_test())
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["mode"] in ("precomputed", "live")


def test_calls():
    from web import api
    async def _test():
        transport = ASGITransport(app=api.app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            return await ac.get("/calls")
    resp = _run(_test())
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


def test_transcripts_shape():
    from web import api
    async def _test():
        transport = ASGITransport(app=api.app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            calls_resp = await ac.get("/calls")
            calls = calls_resp.json()
            if calls and isinstance(calls, list) and len(calls) > 0:
                call_id = calls[0].get("call_id") or "c01"
            else:
                call_id = "c01"
            return await ac.get(f"/calls/{call_id}/transcripts")
    resp = _run(_test())
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    for key in ("baseline", "mismatched", "adaptive", "oracle"):
        assert key in data
        assert isinstance(data[key], list)
        for token in data[key]:
            assert isinstance(token, dict)
            assert "text" in token
            assert "status" in token
            assert token["status"] in ("same", "missed", "recovered", "inserted")


def test_results_shape():
    from web import api
    async def _test():
        transport = ASGITransport(app=api.app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            return await ac.get("/results")
    resp = _run(_test())
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    assert "contrasts" in data
    assert "control" in data
    assert isinstance(data["contrasts"], list)


def test_outbound_guard_raises():
    from web import api

    os.environ["DEMO_MODE"] = "precomputed"
    import importlib

    importlib.reload(api)
    guard = getattr(api.app.state, "no_outbound_call", None)
    assert guard is not None
    with pytest.raises(RuntimeError):
        guard()
