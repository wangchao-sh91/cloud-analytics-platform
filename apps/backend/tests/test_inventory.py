"""Integration tests: TEST_DATABASE_URL must refer to a disposable PostgreSQL database."""
import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def clean_database():
    command.upgrade(Config("alembic.ini"), "head")
    command.upgrade(Config("alembic.ini"), "head")
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE physical_servers"))


client = TestClient(app)


def create(**values):
    payload = {"name": "实验室服务器", "service_tag": str(uuid4())[:8], "model": "R750", **values}
    response = client.post("/api/servers", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_crud_and_timestamps():
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200
    server = create(service_tag=" abc123 ", owner="张三", notes="中文备注")
    assert server["service_tag"] == "ABC123"
    assert server["status"] == "available"
    assert client.get(f"/api/servers/{server['id']}").json()["notes"] == "中文备注"
    updated = client.patch(f"/api/servers/{server['id']}", json={"status": "retired", "owner": None}).json()
    assert updated["owner"] is None and updated["status"] == "retired"
    assert updated["created_at"] == server["created_at"]
    assert updated["updated_at"] > server["updated_at"]
    assert updated["name"] == server["name"]
    assert client.get("/api/servers?status=retired").json()["total"] == 1
    assert client.delete(f"/api/servers/{server['id']}").status_code == 204
    assert client.get(f"/api/servers/{server['id']}").status_code == 404
    assert client.delete(f"/api/servers/{server['id']}").status_code == 404


def test_duplicates_create_and_update_and_database_constraint():
    first = create(service_tag="ABC123")
    second = create(service_tag="OTHER")
    assert client.post("/api/servers", json={"name":"x", "model":"x", "service_tag":" abc123 "}).status_code == 409
    assert client.patch(f"/api/servers/{second['id']}", json={"service_tag":"abc123"}).status_code == 409
    assert client.get(f"/api/servers/{second['id']}").json()["service_tag"] == "OTHER"
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO physical_servers SELECT :id, name, service_tag, model, management_ip, idrac_ip, lab, rack, owner, rack_unit, cpu_summary, memory_summary, disk_summary, purpose, notes, status, created_at, updated_at FROM physical_servers WHERE id = :source"), {"id":uuid4(), "source":first["id"]})


@pytest.mark.parametrize("value", [
    {"name":" "}, {"model":None}, {"service_tag":""}, {"management_ip":"not-an-ip"},
    {"idrac_ip":"1.2.3"}, {"rack_unit":0}, {"rack_unit":1.5}, {"status":"online"},
    {"notes":"x"*10001}, {"id":str(uuid4())}, {"name":"x"*256},
])
def test_invalid_creation(value):
    response = client.post("/api/servers", json={"name":"test", "model":"R750", "service_tag":"TEST", **value})
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert response.json()["field_errors"]
    assert client.get("/api/servers").json()["total"] == 0


def test_patch_required_null_and_optional_empty():
    server = create(management_ip="2001:db8::1", lab="Lab A")
    for value in [{"name":None}, {"service_tag":None}, {"model":None}, {"status":None}, {"created_at":"2020-01-01"}]:
        assert client.patch(f"/api/servers/{server['id']}", json=value).status_code == 422
    result = client.patch(f"/api/servers/{server['id']}", json={"lab":" "}).json()
    assert result["lab"] is None and result["management_ip"] == "2001:db8::1"


def test_search_filters_pagination_and_literal_wildcards():
    create(name="alpha_100%", service_tag="TAG-A", management_ip="10.0.0.1", idrac_ip="10.1.0.1", status="in_use")
    create(name="alpha2100x", model="R740")
    create(name="another", status="maintenance")
    for q in ["TAG-a", "10.0.0", "10.1.0", "_", "%"]:
        assert client.get("/api/servers", params={"q":q}).json()["total"] == 1
    result = client.get("/api/servers", params={"q":"ALPHA", "model":"R750", "status":"in_use", "page_size":1}).json()
    assert result["total"] == 1 and len(result["items"]) == 1
    assert client.get("/api/servers?page=99").json()["items"] == []
    assert client.get("/api/servers?q=missing").json()["total"] == 0
    pages = [client.get(f"/api/servers?page={i}&page_size=1").json()["items"][0]["id"] for i in range(1,4)]
    assert len(set(pages)) == 3
    for query in ["page=0", "page_size=101", "page_size=0", "status=online"]:
        assert client.get(f"/api/servers?{query}").status_code == 422


def test_missing_and_bad_ids():
    path = f"/api/servers/{uuid4()}"
    assert client.get(path).status_code == 404
    assert client.patch(path, json={"name":"new"}).status_code == 404
    assert client.delete(path).status_code == 404
    assert client.get("/api/servers/not-a-uuid").status_code == 422


def test_readiness_with_wrong_revision():
    with engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num='outdated'"))
    try:
        assert client.get("/health/ready").status_code == 503
        assert client.get("/health/live").status_code == 200
    finally:
        with engine.begin() as connection:
            connection.execute(text("UPDATE alembic_version SET version_num='001_inventory'"))
