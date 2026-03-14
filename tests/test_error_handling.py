from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.config import settings
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
    UnauthorizedException,
)
from app.main import app

client = TestClient(app, raise_server_exceptions=False)


# Mock endpoints to trigger exceptions
@app.get("/test/bad-request")
async def trigger_bad_request():
    raise BadRequestException(message="Custom bad request message")


@app.get("/test/unauthorized")
async def trigger_unauthorized():
    raise UnauthorizedException()


@app.get("/test/forbidden")
async def trigger_forbidden():
    raise ForbiddenException()


@app.get("/test/not-found")
async def trigger_not_found():
    raise NotFoundException()


@app.get("/test/conflict")
async def trigger_conflict():
    raise ConflictException()


@app.get("/test/http-exception")
async def trigger_http_exception():
    raise HTTPException(status_code=418, detail="I'm a teapot")


@app.get("/test/unhandled-exception")
async def trigger_unhandled_exception():
    raise ValueError("Something went wrong internally")


class ValidationModel(BaseModel):
    name: str
    age: int


@app.post("/test/validation")
async def trigger_validation_error(data: ValidationModel):
    return data


def test_bad_request_handler():
    response = client.get("/test/bad-request")
    assert response.status_code == 400
    data = response.json()
    assert data["status"] == "error"
    assert data["code"] == "BAD_REQUEST"
    assert data["message"] == "Custom bad request message"


def test_unauthorized_handler():
    response = client.get("/test/unauthorized")
    assert response.status_code == 401
    data = response.json()
    assert data["code"] == "UNAUTHORIZED"


def test_forbidden_handler():
    response = client.get("/test/forbidden")
    assert response.status_code == 403
    data = response.json()
    assert data["code"] == "FORBIDDEN"


def test_not_found_handler():
    response = client.get("/test/not-found")
    assert response.status_code == 404
    data = response.json()
    assert data["code"] == "NOT_FOUND"


def test_conflict_handler():
    response = client.get("/test/conflict")
    assert response.status_code == 409
    data = response.json()
    assert data["code"] == "CONFLICT"


def test_http_exception_handler():
    response = client.get("/test/http-exception")
    assert response.status_code == 418
    data = response.json()
    assert data["status"] == "error"
    assert data["message"] == "I'm a teapot"


def test_validation_error_handler():
    # Missing required fields
    response = client.post("/test/validation", json={"age": "not-an-int"})
    assert response.status_code == 400
    data = response.json()
    assert data["status"] == "error"
    assert data["code"] == "VALIDATION_ERROR"
    assert len(data["details"]) > 0
    # Check if field name is present in details
    fields = [d["field"] for d in data["details"]]
    assert "body.name" in fields
    assert "body.age" in fields


def test_unhandled_exception_handler():
    response = client.get("/test/unhandled-exception")
    assert response.status_code == 500
    data = response.json()
    assert data["status"] == "error"
    assert data["code"] == "INTERNAL_SERVER_ERROR"
    assert data["message"] == "An unexpected server error occurred"


def test_health_check_remains_ok():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in {"ok", "degraded"}  # depends on whether Kafka is running
    assert data["version"] == settings.VERSION
    assert "services" in data
