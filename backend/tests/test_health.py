def test_health_check(client):
    """Verify that GET /health returns 200 and healthy status."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_root(client):
    """Verify that root endpoint responds."""
    response = client.get("/")
    assert response.status_code == 200
    assert "message" in response.json()


def test_cors_headers(client):
    """Verify CORS headers are returned for allowed origins."""
    headers = {
        "Origin": "http://localhost:3000",
        "Access-Control-Request-Method": "GET",
    }
    response = client.options("/health", headers=headers)
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_readiness(client):
    assert client.get("/ready").status_code == 200


def test_readiness_database_failure(client, monkeypatch, db_session):
    from sqlalchemy.exc import OperationalError

    def fail(*args, **kwargs):
        raise OperationalError("query", {}, Exception("private connection details"))

    monkeypatch.setattr(db_session, "execute", fail)
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database is not ready"}


def test_readiness_requires_research_schema(client, db_session):
    from sqlalchemy import text

    db_session.execute(text("DROP TABLE research_job_sources"))
    db_session.commit()
    assert client.get("/ready").status_code == 503


def test_cors_rejects_unknown_origin(client):
    response = client.options("/health", headers={
        "Origin": "https://untrusted.example",
        "Access-Control-Request-Method": "GET",
    })
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
