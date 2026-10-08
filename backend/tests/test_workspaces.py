def get_auth_headers(client, email="test@example.com", password="password123"):
    """Helper to register and login a user and return Authorization headers."""
    client.post("/auth/register", json={"email": email, "password": password})
    login_res = client.post("/auth/login", json={"email": email, "password": password})
    token = login_res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_create_workspace_success(client):
    headers = get_auth_headers(client)
    response = client.post(
        "/workspaces",
        headers=headers,
        json={"name": "Research Project", "description": "Notes and research files"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Research Project"
    assert data["description"] == "Notes and research files"
    assert "id" in data
    assert "user_id" in data
    assert "created_at" in data


def test_create_workspace_unauthenticated(client):
    response = client.post(
        "/workspaces",
        json={"name": "Unauthorized Workspace"},
    )
    assert response.status_code == 401


def test_create_workspace_validation(client):
    headers = get_auth_headers(client)
    # Empty name should fail
    response = client.post(
        "/workspaces",
        headers=headers,
        json={"name": ""},
    )
    assert response.status_code == 422


def test_list_workspaces(client):
    headers1 = get_auth_headers(client, email="user1@example.com")
    headers2 = get_auth_headers(client, email="user2@example.com")

    # Create 2 workspaces for user 1
    client.post("/workspaces", headers=headers1, json={"name": "WS 1"})
    client.post("/workspaces", headers=headers1, json={"name": "WS 2"})

    # Create 1 workspace for user 2
    client.post("/workspaces", headers=headers2, json={"name": "WS User 2"})

    # User 1 should only see their 2 workspaces
    res1 = client.get("/workspaces", headers=headers1)
    assert res1.status_code == 200
    workspaces1 = res1.json()
    assert len(workspaces1) == 2
    names1 = [ws["name"] for ws in workspaces1]
    assert "WS 1" in names1
    assert "WS 2" in names1

    # User 2 should only see their 1 workspace
    res2 = client.get("/workspaces", headers=headers2)
    assert res2.status_code == 200
    workspaces2 = res2.json()
    assert len(workspaces2) == 1
    assert workspaces2[0]["name"] == "WS User 2"


def test_get_workspace_by_id(client):
    headers = get_auth_headers(client)
    create_res = client.post(
        "/workspaces",
        headers=headers,
        json={"name": "Target Workspace", "description": "Specific details"},
    )
    ws_id = create_res.json()["id"]

    get_res = client.get(f"/workspaces/{ws_id}", headers=headers)
    assert get_res.status_code == 200
    data = get_res.json()
    assert data["id"] == ws_id
    assert data["name"] == "Target Workspace"


def test_get_workspace_not_found_or_forbidden(client):
    headers1 = get_auth_headers(client, email="owner@example.com")
    headers2 = get_auth_headers(client, email="other@example.com")

    create_res = client.post(
        "/workspaces",
        headers=headers1,
        json={"name": "Owner Workspace"},
    )
    ws_id = create_res.json()["id"]

    # Other user trying to access owner's workspace gets 404
    other_res = client.get(f"/workspaces/{ws_id}", headers=headers2)
    assert other_res.status_code == 404

    # Random non-existent UUID gets 404
    non_existent = "00000000-0000-0000-0000-000000000000"
    missing_res = client.get(f"/workspaces/{non_existent}", headers=headers1)
    assert missing_res.status_code == 404


def test_delete_workspace(client):
    headers = get_auth_headers(client)
    create_res = client.post(
        "/workspaces",
        headers=headers,
        json={"name": "To Delete"},
    )
    ws_id = create_res.json()["id"]

    # Delete workspace
    delete_res = client.delete(f"/workspaces/{ws_id}", headers=headers)
    assert delete_res.status_code == 204

    # Subsequent GET returns 404
    get_res = client.get(f"/workspaces/{ws_id}", headers=headers)
    assert get_res.status_code == 404


def test_delete_workspace_not_owner(client):
    headers1 = get_auth_headers(client, email="owner_del@example.com")
    headers2 = get_auth_headers(client, email="attacker@example.com")

    create_res = client.post(
        "/workspaces",
        headers=headers1,
        json={"name": "Protected Workspace"},
    )
    ws_id = create_res.json()["id"]

    # Attacker tries to delete
    delete_res = client.delete(f"/workspaces/{ws_id}", headers=headers2)
    assert delete_res.status_code == 404

    # Verify workspace still exists for owner
    get_res = client.get(f"/workspaces/{ws_id}", headers=headers1)
    assert get_res.status_code == 200
