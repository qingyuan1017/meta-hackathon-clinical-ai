import pytest

from bioportal_mcp import server


async def test_get_class_encodes_full_iri_as_one_path_segment(monkeypatch) -> None:
    captured = {}

    async def fake_get(endpoint: str, *, params=None):
        captured["endpoint"] = endpoint
        captured["params"] = params
        return {"prefLabel": "Melanoma"}

    monkeypatch.setattr(server, "_get", fake_get)

    result = await server.bioportal_get_class(
        "ncit",
        "http://ncicb.nci.nih.gov/xml/owl/EVS/Thesaurus.owl#C3224",
    )

    assert result == {"prefLabel": "Melanoma"}
    assert captured["endpoint"] == (
        "/ontologies/NCIT/classes/"
        "http%3A%2F%2Fncicb.nci.nih.gov%2Fxml%2Fowl%2FEVS%2FThesaurus.owl%23C3224"
    )


async def test_search_uses_bioportal_parameter_names(monkeypatch) -> None:
    captured = {}

    async def fake_get(endpoint: str, *, params=None):
        captured["endpoint"] = endpoint
        captured["params"] = params
        return {"collection": []}

    monkeypatch.setattr(server, "_get", fake_get)

    await server.bioportal_search_classes(
        "asthma",
        ontologies=["ncit", "snomedct"],
        require_exact_match=True,
        page=2,
        page_size=15,
    )

    assert captured["endpoint"] == "/search"
    assert captured["params"]["ontologies"] == "NCIT,SNOMEDCT"
    assert captured["params"]["require_exact_match"] is True
    assert captured["params"]["pagesize"] == 15
    assert captured["params"]["page"] == 2


async def test_recommender_bounds_returned_list(monkeypatch) -> None:
    async def fake_get(endpoint: str, *, params=None):
        assert endpoint == "/recommender"
        return [{"score": index} for index in range(8)]

    monkeypatch.setattr(server, "_get", fake_get)

    result = await server.bioportal_recommend_ontologies("melanoma", max_results=3)

    assert result == [{"score": 0}, {"score": 1}, {"score": 2}]


async def test_annotator_bounds_returned_list(monkeypatch) -> None:
    async def fake_get(endpoint: str, *, params=None):
        assert endpoint == "/annotator"
        return [{"annotation": index} for index in range(8)]

    monkeypatch.setattr(server, "_get", fake_get)

    result = await server.bioportal_annotate_text("melanoma", max_results=3)

    assert result == [{"annotation": 0}, {"annotation": 1}, {"annotation": 2}]


async def test_mapping_lookup_requests_mapping_attributes(monkeypatch) -> None:
    captured = {}

    async def fake_get(endpoint: str, *, params=None):
        captured["endpoint"] = endpoint
        captured["params"] = params
        return []

    monkeypatch.setattr(server, "_get", fake_get)

    await server.bioportal_get_class_related(
        "NCIT",
        "http://ncicb.nci.nih.gov/xml/owl/EVS/Thesaurus.owl#C3224",
        "mappings",
    )

    assert captured["endpoint"].endswith("/mappings")
    assert captured["params"]["include"] == "classes,process,source"


@pytest.mark.parametrize("class_id", ["", "C3224", "ftp://example.test/C3224"])
def test_class_id_requires_absolute_http_iri(class_id: str) -> None:
    with pytest.raises(ValueError):
        server._class_id(class_id)
