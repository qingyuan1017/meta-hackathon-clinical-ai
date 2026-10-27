from __future__ import annotations

import asyncio
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from datetime import date
from typing import Any

import httpx

from .config import Settings, get_settings

RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}
ALLOWED_ENDPOINTS = {"einfo.fcgi", "esearch.fcgi", "efetch.fcgi"}
PMID_PATTERN = re.compile(r"[1-9]\d{0,9}")
DATE_PATTERN = re.compile(r"\d{4}(?:/\d{2}(?:/\d{2})?)?")
TOOL_PATTERN = re.compile(r"[A-Za-z0-9._-]+")
SORT_ORDERS = {"relevance", "pub_date", "Author", "JournalName"}
DATE_TYPES = {"pdat", "edat", "mdat"}


class PubMedError(RuntimeError):
    """A safe, user-facing error from NCBI E-utilities or response parsing."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class PubMedConfigurationError(PubMedError):
    """Raised when NCBI-required client identification is not configured."""


def _node_text(node: ET.Element | None) -> str | None:
    if node is None:
        return None
    value = " ".join("".join(node.itertext()).split())
    return value or None


def _date_text(parent: ET.Element | None) -> str | None:
    if parent is None:
        return None
    medline_date = _node_text(parent.find("./MedlineDate"))
    if medline_date:
        return medline_date
    parts = [
        _node_text(parent.find("./Year")),
        _node_text(parent.find("./Month")),
        _node_text(parent.find("./Day")),
    ]
    return " ".join(part for part in parts if part) or None


def _validate_search_date(value: str, label: str) -> str:
    candidate = value.strip()
    if not DATE_PATTERN.fullmatch(candidate):
        raise ValueError(f"{label} must use YYYY, YYYY/MM, or YYYY/MM/DD")
    parts = [int(part) for part in candidate.split("/")]
    try:
        date(
            parts[0],
            parts[1] if len(parts) > 1 else 1,
            parts[2] if len(parts) > 2 else 1,
        )
    except ValueError as exc:
        raise ValueError(f"{label} must be a valid calendar date") from exc
    return candidate


def _authors(article: ET.Element) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for author in article.findall("./AuthorList/Author"):
        collective = _node_text(author.find("./CollectiveName"))
        last_name = _node_text(author.find("./LastName"))
        fore_name = _node_text(author.find("./ForeName"))
        initials = _node_text(author.find("./Initials"))
        name = collective or " ".join(part for part in (fore_name, last_name) if part)
        if not name:
            name = " ".join(part for part in (last_name, initials) if part)
        affiliations = [
            value
            for item in author.findall("./AffiliationInfo/Affiliation")
            if (value := _node_text(item))
        ]
        if name:
            result.append(
                {
                    "name": name,
                    "last_name": last_name,
                    "fore_name": fore_name,
                    "initials": initials,
                    "collective_name": collective,
                    "affiliations": affiliations,
                }
            )
    return result


def _abstract(article: ET.Element) -> tuple[str | None, list[dict[str, str]]]:
    sections: list[dict[str, str]] = []
    rendered: list[str] = []
    for item in article.findall("./Abstract/AbstractText"):
        text = _node_text(item)
        if not text:
            continue
        label = (
            item.attrib.get("Label") or item.attrib.get("NlmCategory") or ""
        ).strip()
        section: dict[str, str] = {"text": text}
        if label:
            section["label"] = label
            rendered.append(f"{label}: {text}")
        else:
            rendered.append(text)
        sections.append(section)
    return ("\n".join(rendered) or None, sections)


def parse_pubmed_xml(value: str) -> list[dict[str, Any]]:
    """Convert NCBI PubMedArticle XML into bounded, model-friendly records."""

    try:
        root = ET.fromstring(value)
    except ET.ParseError as exc:
        raise PubMedError("PubMed returned malformed XML.") from exc

    records: list[dict[str, Any]] = []
    for record in root.findall("./PubmedArticle"):
        citation = record.find("./MedlineCitation")
        article = citation.find("./Article") if citation is not None else None
        if citation is None or article is None:
            continue

        pmid = _node_text(citation.find("./PMID"))
        if not pmid:
            continue
        abstract, abstract_sections = _abstract(article)
        article_ids = {
            id_type: identifier
            for item in record.findall("./PubmedData/ArticleIdList/ArticleId")
            if (id_type := item.attrib.get("IdType", "").strip().lower())
            and (identifier := _node_text(item))
        }
        publication_date = _date_text(article.find("./Journal/JournalIssue/PubDate"))
        if not publication_date:
            publication_date = _date_text(article.find("./ArticleDate"))

        mesh_terms: list[str] = []
        for heading in citation.findall("./MeshHeadingList/MeshHeading"):
            descriptor = _node_text(heading.find("./DescriptorName"))
            qualifiers = [
                value
                for item in heading.findall("./QualifierName")
                if (value := _node_text(item))
            ]
            if descriptor:
                mesh_terms.append(
                    f"{descriptor} / {', '.join(qualifiers)}"
                    if qualifiers
                    else descriptor
                )

        records.append(
            {
                "pmid": pmid,
                "title": _node_text(article.find("./ArticleTitle")),
                "abstract": abstract,
                "abstract_sections": abstract_sections,
                "authors": _authors(article),
                "journal": _node_text(article.find("./Journal/Title")),
                "journal_abbreviation": _node_text(
                    article.find("./Journal/ISOAbbreviation")
                ),
                "publication_date": publication_date,
                "volume": _node_text(article.find("./Journal/JournalIssue/Volume")),
                "issue": _node_text(article.find("./Journal/JournalIssue/Issue")),
                "pages": _node_text(article.find("./Pagination/MedlinePgn")),
                "language": _node_text(article.find("./Language")),
                "publication_types": [
                    value
                    for item in article.findall("./PublicationTypeList/PublicationType")
                    if (value := _node_text(item))
                ],
                "mesh_terms": mesh_terms,
                "keywords": [
                    value
                    for item in citation.findall("./KeywordList/Keyword")
                    if (value := _node_text(item))
                ],
                "doi": article_ids.get("doi"),
                "pmc_id": article_ids.get("pmc"),
                "pubmed_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            }
        )
    return records


class PubMedClient:
    """Async, read-only client for PubMed through NCBI Entrez E-utilities."""

    def __init__(
        self,
        email: str,
        *,
        api_key: str = "",
        tool: str = "clinical_ai_pubmed_mcp",
        base_url: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils",
        timeout_seconds: float = 30.0,
        max_results: int = 20,
        transport: httpx.AsyncBaseTransport | None = None,
        request_interval_seconds: float | None = None,
    ) -> None:
        self.email = email.strip()
        self.api_key = api_key.strip()
        self.tool = tool.strip()
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout_seconds = timeout_seconds
        self.max_results = max_results
        self._transport = transport
        self._rate_lock = asyncio.Lock()
        self._last_request_at = 0.0
        self._request_interval_seconds = (
            request_interval_seconds
            if request_interval_seconds is not None
            else (0.11 if self.api_key else 0.34)
        )

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> PubMedClient:
        configured = settings or get_settings()
        return cls(
            configured.pubmed_email,
            api_key=configured.pubmed_api_key,
            tool=configured.pubmed_tool,
            base_url=configured.pubmed_api_base_url,
            timeout_seconds=configured.pubmed_api_timeout_seconds,
            max_results=configured.pubmed_max_results,
        )

    def _identity_params(self) -> dict[str, str]:
        if (
            not self.email
            or "@" not in self.email
            or any(char.isspace() for char in self.email)
        ):
            raise PubMedConfigurationError(
                "PubMed is not configured. Set PUBMED_EMAIL to a valid contact email required by NCBI."
            )
        if not self.tool or not TOOL_PATTERN.fullmatch(self.tool):
            raise PubMedConfigurationError(
                "PUBMED_TOOL must contain only letters, numbers, periods, underscores, or hyphens."
            )
        result = {"tool": self.tool, "email": self.email}
        if self.api_key:
            result["api_key"] = self.api_key
        return result

    async def _throttle(self) -> None:
        async with self._rate_lock:
            loop = asyncio.get_running_loop()
            delay = self._last_request_at + self._request_interval_seconds - loop.time()
            if delay > 0:
                await asyncio.sleep(delay)
            self._last_request_at = loop.time()

    async def _request(
        self,
        endpoint: str,
        *,
        params: dict[str, str | int],
        accept: str,
    ) -> httpx.Response:
        if endpoint not in ALLOWED_ENDPOINTS:
            raise ValueError("endpoint is not an allowed NCBI E-utility")
        request_params: dict[str, str | int] = {**params, **self._identity_params()}
        headers = {"Accept": accept, "User-Agent": f"{self.tool}/0.1"}
        async with httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=self.timeout_seconds,
            follow_redirects=False,
            transport=self._transport,
        ) as client:
            response: httpx.Response | None = None
            for attempt in range(3):
                await self._throttle()
                try:
                    response = await client.get(endpoint, params=request_params)
                except httpx.RequestError as exc:
                    if attempt == 2:
                        raise PubMedError(
                            "Could not reach NCBI PubMed. Check the base URL, network, and proxy settings."
                        ) from exc
                    await asyncio.sleep(0.25 * (2**attempt))
                    continue
                if response.status_code not in RETRYABLE_STATUS_CODES or attempt == 2:
                    break
                retry_after = response.headers.get("Retry-After", "")
                try:
                    delay = (
                        min(float(retry_after), 5.0)
                        if retry_after
                        else 0.25 * (2**attempt)
                    )
                except ValueError:
                    delay = 0.25 * (2**attempt)
                await asyncio.sleep(delay)

        if response is None:  # pragma: no cover - defensive
            raise PubMedError("The PubMed request did not return a response.")
        if response.is_error:
            raise self._response_error(response)
        return response

    async def _get_json(
        self, endpoint: str, *, params: dict[str, str | int]
    ) -> dict[str, Any]:
        response = await self._request(
            endpoint, params=params, accept="application/json"
        )
        try:
            value = response.json()
        except ValueError as exc:
            raise PubMedError(
                "PubMed returned a non-JSON response.", status_code=response.status_code
            ) from exc
        if not isinstance(value, dict):
            raise PubMedError(
                "PubMed returned an unexpected JSON value.",
                status_code=response.status_code,
            )
        return value

    async def api_info(self) -> dict[str, Any]:
        return await self._get_json(
            "einfo.fcgi", params={"db": "pubmed", "retmode": "json", "version": "2.0"}
        )

    async def search(
        self,
        query: str,
        *,
        limit: int = 5,
        offset: int = 0,
        sort: str = "relevance",
        date_type: str | None = None,
        min_date: str | None = None,
        max_date: str | None = None,
    ) -> dict[str, Any]:
        cleaned_query = query.strip()
        if not cleaned_query:
            raise ValueError("query must not be empty")
        if len(cleaned_query) > 2000:
            raise ValueError("query must be 2000 characters or fewer")
        if not 1 <= limit <= self.max_results:
            raise ValueError(f"limit must be between 1 and {self.max_results}")
        if offset < 0 or offset + limit > 10_000:
            raise ValueError(
                "offset plus limit must be between 1 and PubMed's 10,000-result ESearch cap"
            )
        if (min_date is None) != (max_date is None):
            raise ValueError("min_date and max_date must be supplied together")
        if sort not in SORT_ORDERS:
            raise ValueError(f"sort must be one of {', '.join(sorted(SORT_ORDERS))}")
        if date_type is not None and date_type not in DATE_TYPES:
            raise ValueError("date_type must be pdat, edat, or mdat")
        if date_type is not None and min_date is None:
            raise ValueError("date_type may only be used with min_date and max_date")

        params: dict[str, str | int] = {
            "db": "pubmed",
            "term": cleaned_query,
            "retmode": "json",
            "retstart": offset,
            "retmax": limit,
            "sort": sort,
        }
        if min_date is not None and max_date is not None:
            normalized_min_date = _validate_search_date(min_date, "min_date")
            normalized_max_date = _validate_search_date(max_date, "max_date")
            params.update(
                {
                    "datetype": date_type or "pdat",
                    "mindate": normalized_min_date,
                    "maxdate": normalized_max_date,
                }
            )
        payload = await self._get_json("esearch.fcgi", params=params)
        top_level_error = payload.get("error") or payload.get("ERROR")
        if top_level_error:
            raise PubMedError(f"PubMed ESearch rejected the query: {top_level_error}")
        search_result = payload.get("esearchresult")
        if not isinstance(search_result, dict):
            raise PubMedError("PubMed ESearch returned an unexpected response shape.")
        search_error = search_result.get("error") or search_result.get("ERROR")
        if search_error:
            raise PubMedError(f"PubMed ESearch rejected the query: {search_error}")
        ids_value = search_result.get("idlist", [])
        if not isinstance(ids_value, list):
            raise PubMedError("PubMed ESearch returned an invalid identifier list.")
        pmids = [self.normalize_pmid(str(value)) for value in ids_value]
        articles = await self.fetch(pmids) if pmids else []
        returned_pmids = {article["pmid"] for article in articles}
        try:
            total = int(search_result.get("count", 0))
        except (TypeError, ValueError):
            total = 0
        return {
            "query": cleaned_query,
            "query_translation": search_result.get("querytranslation"),
            "total_count": total,
            "offset": offset,
            "returned_count": len(articles),
            "pmids": pmids,
            "missing_pmids": [pmid for pmid in pmids if pmid not in returned_pmids],
            "articles": articles,
            "warnings": search_result.get("warninglist"),
        }

    async def fetch(self, pmids: Iterable[str]) -> list[dict[str, Any]]:
        normalized: list[str] = []
        for value in pmids:
            pmid = self.normalize_pmid(value)
            if pmid not in normalized:
                normalized.append(pmid)
        if not normalized:
            raise ValueError("pmids must contain at least one PMID")
        if len(normalized) > self.max_results:
            raise ValueError(
                f"pmids must contain at most {self.max_results} unique values"
            )
        response = await self._request(
            "efetch.fcgi",
            params={"db": "pubmed", "id": ",".join(normalized), "retmode": "xml"},
            accept="application/xml",
        )
        return parse_pubmed_xml(response.text)

    @staticmethod
    def normalize_pmid(value: str) -> str:
        candidate = value.strip()
        if not PMID_PATTERN.fullmatch(candidate):
            raise ValueError(
                "each PMID must contain 1 to 10 digits and may not start with zero"
            )
        return candidate

    def _response_error(self, response: httpx.Response) -> PubMedError:
        detail = " ".join(response.text.split())[:500]
        if self.api_key:
            detail = detail.replace(self.api_key, "[REDACTED]")
        if response.status_code in {401, 403}:
            message = "NCBI rejected the PubMed API key or request identity."
        elif response.status_code == 404:
            message = "The requested NCBI PubMed resource was not found."
        elif response.status_code == 429:
            message = "NCBI PubMed rate limit exceeded. Retry later or configure PUBMED_API_KEY."
        else:
            message = f"NCBI PubMed returned HTTP {response.status_code}."
        if detail:
            message = f"{message} {detail}"
        return PubMedError(message, status_code=response.status_code)
