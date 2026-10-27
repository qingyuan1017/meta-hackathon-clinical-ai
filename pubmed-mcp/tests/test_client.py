from __future__ import annotations

import httpx
import pytest

from pubmed_mcp.client import (
    PubMedClient,
    PubMedConfigurationError,
    PubMedError,
    parse_pubmed_xml,
)

SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID Version="1">12345678</PMID>
      <Article>
        <Journal>
          <ISSN>1234-5678</ISSN>
          <JournalIssue>
            <Volume>12</Volume><Issue>3</Issue>
            <PubDate><Year>2025</Year><Month>Oct</Month><Day>2</Day></PubDate>
          </JournalIssue>
          <Title>Journal of Tests</Title><ISOAbbreviation>J Test</ISOAbbreviation>
        </Journal>
        <ArticleTitle>A <i>structured</i> trial result</ArticleTitle>
        <Pagination><MedlinePgn>10-18</MedlinePgn></Pagination>
        <Abstract>
          <AbstractText Label="BACKGROUND">Background text.</AbstractText>
          <AbstractText Label="RESULTS">Result with <b>markup</b>.</AbstractText>
        </Abstract>
        <AuthorList>
          <Author><LastName>Ng</LastName><ForeName>Ada</ForeName><Initials>A</Initials>
            <AffiliationInfo><Affiliation>Example University</Affiliation></AffiliationInfo>
          </Author>
          <Author><CollectiveName>Study Group</CollectiveName></Author>
        </AuthorList>
        <Language>eng</Language>
        <PublicationTypeList><PublicationType>Randomized Controlled Trial</PublicationType></PublicationTypeList>
      </Article>
      <MeshHeadingList><MeshHeading><DescriptorName>Asthma</DescriptorName><QualifierName>therapy</QualifierName></MeshHeading></MeshHeadingList>
      <KeywordList><Keyword>synthetic</Keyword></KeywordList>
    </MedlineCitation>
    <PubmedData><ArticleIdList>
      <ArticleId IdType="pubmed">12345678</ArticleId>
      <ArticleId IdType="doi">10.1000/example</ArticleId>
      <ArticleId IdType="pmc">PMC1234</ArticleId>
    </ArticleIdList></PubmedData>
  </PubmedArticle>
</PubmedArticleSet>
"""


def test_parse_pubmed_xml_preserves_mixed_text_and_identifiers() -> None:
    articles = parse_pubmed_xml(SAMPLE_XML)

    assert len(articles) == 1
    article = articles[0]
    assert article["pmid"] == "12345678"
    assert article["title"] == "A structured trial result"
    assert article["abstract"] == (
        "BACKGROUND: Background text.\nRESULTS: Result with markup."
    )
    assert article["authors"][0]["name"] == "Ada Ng"
    assert article["authors"][1]["collective_name"] == "Study Group"
    assert article["publication_date"] == "2025 Oct 2"
    assert article["mesh_terms"] == ["Asthma / therapy"]
    assert article["doi"] == "10.1000/example"
    assert article["pmc_id"] == "PMC1234"


async def test_search_uses_esearch_then_xml_efetch_with_ncbi_identity() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.params["db"] == "pubmed"
        assert request.url.params["tool"] == "test_pubmed_mcp"
        assert request.url.params["email"] == "owner@example.com"
        assert request.url.params["api_key"] == "secret-key"
        if request.url.path.endswith("/esearch.fcgi"):
            assert request.url.params["term"] == "asthma[Title]"
            assert request.url.params["retmax"] == "1"
            return httpx.Response(
                200,
                json={
                    "esearchresult": {
                        "count": "1",
                        "idlist": ["12345678"],
                        "querytranslation": '"asthma"[Title]',
                    }
                },
            )
        assert request.url.path.endswith("/efetch.fcgi")
        assert request.url.params["id"] == "12345678"
        return httpx.Response(200, text=SAMPLE_XML)

    client = PubMedClient(
        "owner@example.com",
        api_key="secret-key",
        tool="test_pubmed_mcp",
        transport=httpx.MockTransport(handler),
        request_interval_seconds=0,
    )
    result = await client.search("asthma[Title]", limit=1)

    assert len(requests) == 2
    assert result["total_count"] == 1
    assert result["pmids"] == ["12345678"]
    assert result["articles"][0]["doi"] == "10.1000/example"


async def test_search_with_no_matches_does_not_call_efetch() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.path.endswith("/esearch.fcgi")
        return httpx.Response(200, json={"esearchresult": {"count": "0", "idlist": []}})

    client = PubMedClient(
        "owner@example.com",
        transport=httpx.MockTransport(handler),
        request_interval_seconds=0,
    )
    result = await client.search("definitely-no-results", limit=1)

    assert calls == 1
    assert result["articles"] == []


async def test_client_requires_contact_email_before_request() -> None:
    client = PubMedClient("", request_interval_seconds=0)

    with pytest.raises(PubMedConfigurationError, match="PUBMED_EMAIL"):
        await client.search("asthma")


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"min_date": "2025"}, "supplied together"),
        ({"min_date": "2025/13", "max_date": "2026"}, "valid calendar date"),
        ({"date_type": "pdat"}, "only be used"),
        ({"sort": "newest"}, "sort must be"),
    ],
)
async def test_search_rejects_invalid_pubmed_parameters(
    kwargs: dict, message: str
) -> None:
    client = PubMedClient("owner@example.com", request_interval_seconds=0)

    with pytest.raises(ValueError, match=message):
        await client.search("asthma", **kwargs)


async def test_http_error_redacts_api_key() -> None:
    secret = "do-not-leak"

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text=f"bad key {secret}")

    client = PubMedClient(
        "owner@example.com",
        api_key=secret,
        transport=httpx.MockTransport(handler),
        request_interval_seconds=0,
    )
    with pytest.raises(PubMedError) as exc_info:
        await client.search("asthma", limit=1)

    assert secret not in str(exc_info.value)
    assert "API key" in str(exc_info.value)


@pytest.mark.parametrize("value", ["", "0", "0123", "PMID123", "12.3", "12345678901"])
def test_invalid_pmids_are_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="PMID"):
        PubMedClient.normalize_pmid(value)


def test_malformed_xml_is_a_safe_error() -> None:
    with pytest.raises(PubMedError, match="malformed XML"):
        parse_pubmed_xml("<PubmedArticleSet>")
