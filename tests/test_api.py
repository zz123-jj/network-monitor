import json
import time
import httpx
from fastapi.testclient import TestClient
from backend.app import app


def test_history_query_is_bounded_and_missing_stays_null():
    queries = []

    def handle(request):
        if request.url.path == "/state":
            return httpx.Response(
                200,
                json={
                    "nodes": [{"name": "Tokyo", "host": "1.1.1.1"}],
                    "settings": {
                        "intervals": {"ping": 10, "tcp": 30, "https": 30, "dns": 60, "mtr": 300}
                    },
                },
            )
        queries.append(dict(request.url.params))
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "result": [
                        {
                            "metric": {},
                            "values": [
                                [int(request.url.params["start"]), "NaN"],
                                [
                                    int(request.url.params["start"])
                                    + int(request.url.params["step"]),
                                    "42",
                                ],
                            ],
                        }
                    ]
                },
            },
        )

    with TestClient(app) as client:
        original = app.state.client
        app.state.client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        assert client.get("/api/history?node=arbitrary").status_code == 404
        assert client.get("/api/history?node=Tokyo&range=100d").status_code == 422
        assert client.get("/api/history?node=Tokyo&end=nan").status_code == 422
        response = client.get("/api/history?node=Tokyo&range=30d").json()
        assert response["step"] >= 4320
        assert len(response["series"]["rtt"][0]["points"]) <= 601
        assert response["series"]["rtt"][0]["points"][0][1] is None
        assert all('job="network-probe"' in q["query"] for q in queries)
        assert client.post("/api/probe", json={"host": "evil"}).status_code == 404
        app.state.client = original
