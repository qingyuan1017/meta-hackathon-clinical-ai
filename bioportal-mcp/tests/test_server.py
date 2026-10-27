from mcp import Client

from bioportal_mcp.server import mcp


async def test_mcp_exposes_expected_read_only_tools() -> None:
    async with Client(mcp) as client:
        result = await client.list_tools()

    names = {tool.name for tool in result.tools}
    assert names == {
        "bioportal_status",
        "bioportal_get_ontology",
        "bioportal_search_classes",
        "bioportal_get_class",
        "bioportal_get_class_related",
        "bioportal_annotate_text",
        "bioportal_recommend_ontologies",
    }
