from __future__ import annotations

from fastapi.testclient import TestClient

from plansight.api.app import app, _records
from plansight.api.scene3d import cache_paths
from plansight.config import resolve


client = TestClient(app)


def test_swiss_scene_has_semantic_geometry():
    drawing = next(resolve(item["path"]) for item in _records()["swiss_dwellings"])
    path = next(item["path"] for item in _records()["swiss_dwellings"] if resolve(item["path"]) == drawing)
    response = client.get("/api/scene3d", params={"path": path})
    assert response.status_code == 200
    data = response.json()
    assert data["kind"] == "plan" and data["units"] == "m"
    assert len(data["walls"]) > 10
    assert len(data["doors"]) > 5
    assert any(room["name"] for room in data["rooms"])
    assert len(data["bounds"]) == 4


def test_ifc_scene_glb_contains_model_geometry_and_door_guid():
    item = _records()["ifc_models"][0]
    response = client.get("/api/scene3d", params={"path": item["path"]})
    assert response.status_code == 200
    data = response.json()
    assert data["kind"] == "ifc"
    doors = [e for e in data["elements"] if e["ifc_class"] == "IfcDoor"]
    assert doors
    _, glb = cache_paths(item["path"])
    assert glb.is_file() and glb.stat().st_size < 5 * 1024 * 1024
    import trimesh
    loaded = trimesh.load(glb, force="scene")
    assert loaded.geometry
    names = set(loaded.geometry)
    assert any(door["guid"] in name for door in doors for name in names)
