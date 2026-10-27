from mcp import Client

from cdisc_mcp.server import mcp


async def test_mcp_exposes_expected_read_only_tools() -> None:
    async with Client(mcp) as client:
        result = await client.list_tools()

    names = {tool.name for tool in result.tools}
    assert names == {
        "cdisc_library_status",
        "cdisc_list_products",
        "cdisc_search",
        "cdisc_get_standard",
        "cdisc_get_dataset",
        "cdisc_get_variable",
        "cdisc_list_ct_packages",
        "cdisc_get_codelist",
        "cdisc_list_biomedical_concepts",
        "cdisc_get_biomedical_concept",
        "cdisc_list_sdtm_specializations",
        "cdisc_get_sdtm_specialization",
        "cdisc_read_endpoint",
    }
