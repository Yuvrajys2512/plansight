from fastapi.testclient import TestClient

from plansight.api.app import app
from plansight.eval.data import detect_language


client = TestClient(app)


def _drawing(source: str) -> dict:
    items = client.get("/drawings").json()
    match = next((item for item in items if item["source"] == source), None)
    assert match is not None, f"No solver-correct demo drawing found for {source}"
    return match


def test_curated_drawings_cover_all_sources():
    response = client.get("/drawings")
    assert response.status_code == 200
    rows = response.json()
    assert {row["source"] for row in rows} == {"swiss_dwellings", "ifc_models", "cubicasa5k"}
    assert all(row["path"] and row["title"] and row["thumbnail_url"] for row in rows)


def test_examples_include_samples():
    drawing = _drawing("swiss_dwellings")
    response = client.get("/examples", params={"path": drawing["path"]})
    assert response.status_code == 200
    assert 3 <= len(response.json()["examples"]) <= 5
    examples = response.json()["examples"]
    languages = [detect_language(question) for question in examples]
    assert languages[0] == "en"
    assert any(language not in ("en", "other") for language in languages[1:])


def test_examples_and_ask_for_each_source():
    for source in ("swiss_dwellings", "ifc_models", "cubicasa5k"):
        drawing = _drawing(source)
        examples = client.get("/examples", params={"path": drawing["path"]}).json()["examples"]
        question = drawing.get("sample_question") or examples[0]
        answer = client.post("/ask", json={"path": drawing["path"], "question": question})
        assert answer.status_code == 200
        assert not answer.json().get("abstained"), (source, answer.json())
        assert answer.json().get("evidence"), (source, answer.json())
        assert answer.json()["value"] == drawing["sample_answer"]
        assert answer.json().get("solver")
        assert "latency_ms" in answer.json()
        assert "naive_cost_usd" in answer.json()


def test_normal_miss_abstains_with_200():
    drawing = _drawing("swiss_dwellings")
    response = client.post("/ask", json={"path": drawing["path"], "question": "What color is the architect's pen?"})
    assert response.status_code == 200
    assert response.json()["abstained"] is True
    assert response.json()["reason"]


def test_render_and_meta_use_evidence_coordinate_space():
    drawing = _drawing("cubicasa5k")
    meta = client.get("/meta", params={"path": drawing["path"]})
    image = client.get("/render", params={"path": drawing["path"]})
    assert meta.status_code == 200 and meta.json()["units"] == "px"
    assert image.status_code == 200 and image.headers["content-type"] == "image/png"


def test_ifc_model_requests_return_a_model_fact_card():
    drawing = _drawing("ifc_models")
    model_path = drawing["path"].split("_plan-")[0] + ".ifc"
    response = client.post("/ask", json={"path": model_path, "question": drawing["sample_question"]})
    assert response.status_code == 200
    assert not response.json().get("abstained")
    assert response.json().get("model_fact", {}).get("element")
