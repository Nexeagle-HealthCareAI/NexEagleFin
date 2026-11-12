import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Unit, User, UserUnit
from app.security import clean_phone, hash_pin
from app.seed import seed_tenant


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as session:
        yield session


@pytest.fixture()
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class Group:
    def __init__(self, client, db, name, phone):
        self.client, self.db = client, db
        self.tenant = seed_tenant(db, name, phone, "4321")
        self.owner = self.login(phone, "4321")
        r = client.post("/api/projects", headers=self.owner, json={
            "name": f"{name} Hospital", "units": ["hospital", "diagnostics", "path_lab", "pharmacy"]})
        assert r.status_code == 201, r.text
        self.project = r.json()["id"]
        self.units = {u["kind"]: u["id"] for u in r.json()["units"]}
        me = client.get("/api/me", headers=self.owner).json()
        self.cats = {c["name"]: c["id"] for c in me["categories"]}

    def login(self, phone, pin):
        r = self.client.post("/api/auth/login", json={"phone": phone, "pin": pin})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['token']}"}

    def add_user(self, phone, role, unit_kinds=()):
        u = User(tenant_id=self.tenant.id, name=role, phone=clean_phone(phone), pin_hash=hash_pin("9999"), role=role)
        self.db.add(u)
        self.db.flush()
        for k in unit_kinds:
            self.db.add(UserUnit(user_id=u.id, unit_id=self.units[k]))
        self.db.commit()
        return self.login(phone, "9999")


@pytest.fixture()
def group(client, db):
    return Group(client, db, "City Care Group", "9000000001")


@pytest.fixture()
def other_group(client, db):
    return Group(client, db, "Another Group", "9000000002")
