def test_register_user_success(client):
    """Test successful user registration."""
    response = client.post(
        "/auth/register",
        json={"email": "newuser@example.com", "password": "securepassword123"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "newuser@example.com"
    assert "id" in data
    assert "created_at" in data
    assert "password" not in data
    assert "password_hash" not in data


def test_register_duplicate_email(client):
    """Test that registering an existing email returns 400 Bad Request."""
    user_payload = {"email": "duplicate@example.com", "password": "password123"}
    # First registration
    client.post("/auth/register", json=user_payload)
    # Duplicate attempt
    response = client.post("/auth/register", json=user_payload)
    assert response.status_code == 400
    assert "already registered" in response.json()["detail"].lower()


def test_register_invalid_data(client):
    """Test validation errors for invalid emails or short passwords."""
    # Invalid email format
    response = client.post(
        "/auth/register",
        json={"email": "not-an-email", "password": "password123"},
    )
    assert response.status_code == 422

    # Password too short (< 6 chars)
    response = client.post(
        "/auth/register",
        json={"email": "valid@example.com", "password": "123"},
    )
    assert response.status_code == 422


def test_login_success(client):
    """Test successful login returns a valid JWT token."""
    # Register first
    client.post(
        "/auth/register",
        json={"email": "loginuser@example.com", "password": "mypassword123"},
    )

    # Login
    response = client.post(
        "/auth/login",
        json={"email": "loginuser@example.com", "password": "mypassword123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_login_wrong_password(client):
    """Test login with incorrect password returns 401."""
    client.post(
        "/auth/register",
        json={"email": "user@example.com", "password": "correctpassword"},
    )

    response = client.post(
        "/auth/login",
        json={"email": "user@example.com", "password": "wrongpassword"},
    )
    assert response.status_code == 401
    assert "Invalid email or password" in response.json()["detail"]


def test_login_nonexistent_user(client):
    """Test login with an email that does not exist returns 401."""
    response = client.post(
        "/auth/login",
        json={"email": "nonexistent@example.com", "password": "password123"},
    )
    assert response.status_code == 401
