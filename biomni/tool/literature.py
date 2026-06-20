import os
import re
import time
from io import BytesIO
from urllib.parse import urljoin

import PyPDF2
import requests
from bs4 import BeautifulSoup
from googlesearch import search


def fetch_supplementary_info_from_doi(doi: str, output_dir: str = "supplementary_info"):
    """Fetches supplementary information for a paper given its DOI and returns a research log.

    Args:
        doi: The paper DOI.
        output_dir: Directory to save supplementary files.

    Returns:
        dict: A dictionary containing a research log and the downloaded file paths.

    """
    research_log = []
    research_log.append(f"Starting process for DOI: {doi}")

    # CrossRef API to resolve DOI to a publisher page
    crossref_url = f"https://doi.org/{doi}"
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(crossref_url, headers=headers)

    if response.status_code != 200:
        log_message = f"Failed to resolve DOI: {doi}. Status Code: {response.status_code}"
        research_log.append(log_message)
        return {"log": research_log, "files": []}

    publisher_url = response.url
    research_log.append(f"Resolved DOI to publisher page: {publisher_url}")

    # Fetch publisher page
    response = requests.get(publisher_url, headers=headers)
    if response.status_code != 200:
        log_message = f"Failed to access publisher page for DOI {doi}."
        research_log.append(log_message)
        return {"log": research_log, "files": []}

    # Parse page content
    soup = BeautifulSoup(response.content, "html.parser")
    supplementary_links = []

    # Look for supplementary materials by keywords or links
    for link in soup.find_all("a", href=True):
        href = link.get("href")
        text = link.get_text().lower()
        if "supplementary" in text or "supplemental" in text or "appendix" in text:
            full_url = urljoin(publisher_url, href)
            supplementary_links.append(full_url)
            research_log.append(f"Found supplementary material link: {full_url}")

    if not supplementary_links:
        log_message = f"No supplementary materials found for DOI {doi}."
        research_log.append(log_message)
        return research_log

    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    research_log.append(f"Created output directory: {output_dir}")

    # Download supplementary materials
    downloaded_files = []
    for link in supplementary_links:
        file_name = os.path.join(output_dir, link.split("/")[-1])
        file_response = requests.get(link, headers=headers)
        if file_response.status_code == 200:
            with open(file_name, "wb") as f:
                f.write(file_response.content)
            downloaded_files.append(file_name)
            research_log.append(f"Downloaded file: {file_name}")
        else:
            research_log.append(f"Failed to download file from {link}")

    if downloaded_files:
        research_log.append(f"Successfully downloaded {len(downloaded_files)} file(s).")
    else:
        research_log.append(f"No files could be downloaded for DOI {doi}.")

    return "\n".join(research_log)


def query_arxiv(query: str, max_papers: int = 10) -> str:
    """Query arXiv for papers based on the provided search query.

    Parameters
    ----------
    - query (str): The search query string.
    - max_papers (int): The maximum number of papers to retrieve (default: 10).

    Returns
    -------
    - str: The formatted search results or an error message.

    """
    import arxiv

    try:
        client = arxiv.Client()
        search = arxiv.Search(query=query, max_results=max_papers, sort_by=arxiv.SortCriterion.Relevance)
        results = "\n\n".join([f"Title: {paper.title}\nSummary: {paper.summary}" for paper in client.results(search)])
        return results if results else "No papers found on arXiv."
    except Exception as e:
        return f"Error querying arXiv: {e}"


def query_scholar(query: str) -> str:
    """Query Google Scholar for papers based on the provided search query.

    Parameters
    ----------
    - query (str): The search query string.

    Returns
    -------
    - str: The first search result formatted or an error message.

    """
    from scholarly import ProxyGenerator, scholarly

    # FreeProxies() routes scholarly through public proxies via httpx. In
    # environments with httpx>=0.28 the proxies= kwarg was removed, so the
    # setup raises "Client.__init__() got an unexpected keyword argument
    # 'proxies'" before any query runs. Skip the proxy setup if it fails;
    # scholarly still works against Google Scholar directly, just rate-limited.
    try:
        pg = ProxyGenerator()
        pg.FreeProxies()
        scholarly.use_proxy(pg)
    except Exception as proxy_err:
        print(f"Warning: scholarly proxy setup skipped ({proxy_err}); proceeding without proxies.")

    try:
        search_query = scholarly.search_pubs(query)
        result = next(search_query, None)
        if result:
            return f"Title: {result['bib']['title']}\nYear: {result['bib']['pub_year']}\nVenue: {result['bib']['venue']}\nAbstract: {result['bib']['abstract']}"
        else:
            return "No results found on Google Scholar."
    except Exception as e:
        return f"Error querying Google Scholar: {e}"


_PUBMED_LAST_CALL = [0.0]  # module-level throttle across calls


def _pubmed_throttle(api_key: str | None) -> None:
    # NCBI: 3 req/sec without key, 10 req/sec with key. We're generous.
    min_interval = 0.12 if api_key else 0.4
    elapsed = time.time() - _PUBMED_LAST_CALL[0]
    if elapsed < min_interval:
        time.sleep(min_interval - elapsed)
    _PUBMED_LAST_CALL[0] = time.time()


def _pubmed_request(url: str, params: dict, max_retries: int) -> requests.Response:
    delay = 1.0
    last_err: Exception | None = None
    for attempt in range(max_retries):
        _pubmed_throttle(params.get("api_key"))
        try:
            r = requests.get(url, params=params, timeout=30)
            if r.status_code == 429:
                last_err = requests.exceptions.HTTPError(f"429 Too Many Requests for {url}")
                time.sleep(delay)
                delay *= 2
                continue
            r.raise_for_status()
            return r
        except requests.exceptions.RequestException as e:
            last_err = e
            time.sleep(delay)
            delay *= 2
    raise last_err if last_err else RuntimeError("PubMed request failed")


def query_pubmed(query: str, max_papers: int = 10, max_retries: int = 3) -> str:
    """Query PubMed for papers based on the provided search query.

    Honors environment variables:
      NCBI_EMAIL    - contact email NCBI uses for abuse follow-up (recommended)
      NCBI_API_KEY  - raises rate limit from 3 to 10 req/sec (recommended for loops)

    Parameters
    ----------
    - query (str): The search query string.
    - max_papers (int): The maximum number of papers to retrieve (default: 10).
    - max_retries (int): Per-HTTP-request retry attempts with exponential backoff (default: 3).

    Returns
    -------
    - str: The formatted search results or an error message.

    """
    import xml.etree.ElementTree as ET

    email = os.getenv("NCBI_EMAIL", "your-email@example.com")
    api_key = os.getenv("NCBI_API_KEY") or None

    base_params: dict = {"tool": "biomni", "email": email, "db": "pubmed"}
    if api_key:
        base_params["api_key"] = api_key

    def _search(term: str) -> list[str]:
        params = {**base_params, "term": term, "retmax": max_papers, "retmode": "json"}
        r = _pubmed_request(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi", params, max_retries
        )
        return r.json().get("esearchresult", {}).get("idlist", []) or []

    def _fetch(ids: list[str]) -> list[tuple[str, str, str]]:
        params = {**base_params, "id": ",".join(ids), "retmode": "xml"}
        r = _pubmed_request(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi", params, max_retries
        )
        root = ET.fromstring(r.content)
        out: list[tuple[str, str, str]] = []
        for art in root.findall(".//PubmedArticle"):
            title = "".join(art.find(".//ArticleTitle").itertext()).strip() if art.find(".//ArticleTitle") is not None else ""
            abstract = "\n".join(
                "".join(el.itertext()).strip() for el in art.findall(".//Abstract/AbstractText")
            ).strip()
            journal = (art.findtext(".//Journal/Title") or "").strip()
            out.append((title, abstract, journal))
        return out

    try:
        ids = _search(query)
        # Preserve original behavior: if no hits, retry with progressively simpler query
        attempt = 0
        cur_query = query
        while not ids and attempt < max_retries and len(cur_query.split()) > 1:
            attempt += 1
            cur_query = " ".join(query.split()[:-attempt])
            ids = _search(cur_query)

        if not ids:
            return "No papers found on PubMed after multiple query attempts."

        papers = _fetch(ids)
        return "\n\n".join(
            f"Title: {t}\nAbstract: {a}\nJournal: {j}" for t, a, j in papers
        )
    except Exception as e:
        return f"Error querying PubMed: {e}"


def search_google(query: str, num_results: int = 3, language: str = "en") -> list[dict]:
    """Search using Google search.

    Args:
        query (str): The search query (e.g., "protocol text or seach question")
        num_results (int): Number of results to return (default: 10)
        language (str): Language code for search results (default: 'en')
        pause (float): Pause between searches to avoid rate limiting (default: 2.0 seconds)

    Returns:
        List[dict]: List of dictionaries containing search results with title and URL

    """
    results_string = ""
    search_query = f"{query}"

    print(f"Searching for {search_query} with {num_results} results and {language} language")

    try:
        hits = list(search(search_query, num_results=num_results, lang=language, advanced=True))
    except Exception as e:
        msg = f"Error performing search: {type(e).__name__}: {e}"
        print(msg)
        return msg

    if not hits:
        msg = (
            "No results returned by googlesearch. This usually means Google soft-blocked "
            "this host's IP or returned an empty page. Try again later, reduce frequency, "
            "or switch to a different search backend."
        )
        print(msg)
        return msg

    for res in hits:
        print(f"Found result: {res.title}")
        results_string += f"Title: {res.title}\nURL: {res.url}\nDescription: {res.description}\n\n"

    return results_string


def advanced_web_search_claude(
    query: str,
    max_searches: int = 1,
    max_retries: int = 3,
) -> tuple[str, list[dict[str, str]], list]:
    """
    Initiate an advanced web search by launching a specialized agent to collect relevant information and citations through multiple rounds of web searches for a given query.
    Craft the query carefully for the search agent to find the most relevant information.

    Parameters
    ----------
    query : str
        The search phrase you want Claude to look up.
    max_searches : int, optional
        Upper-bound on searches Claude may issue inside this request.
    max_retries : int, optional
        Maximum number of retry attempts with exponential backoff.

    Returns
    -------
    full_text : str
        A formatted string containing the full text response from Claude and the citations.
    """
    import random

    base_url = None
    try:
        from biomni.config import default_config

        model = default_config.llm
        api_key = default_config.api_key
        base_url = default_config.base_url
        if not api_key:
            api_key = os.getenv("ANTHROPIC_API_KEY")
    except ImportError:
        model = "claude-4-sonnet-latest"
        api_key = os.getenv("ANTHROPIC_API_KEY")

    use_claude = "claude" in (model or "") and bool(api_key)

    if use_claude:
        try:
            import anthropic
        except ImportError:
            use_claude = False

    if use_claude:
        client_kwargs = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        client = anthropic.Anthropic(**client_kwargs)
        tool_def = {
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": max_searches,
        }

        delay = random.randint(1, 10)

        for attempt in range(1, max_retries + 1):
            try:
                response = client.messages.create(
                    model=model,
                    max_tokens=4096,
                    messages=[{"role": "user", "content": query}],
                    tools=[tool_def],
                )

                citations = []
                formatted_response = ""
                for blk in response.content:
                    if blk.type == "text":
                        formatted_response += blk.text
                        if blk.citations:
                            for cite in blk.citations:
                                citations.append({"url": cite.url, "title": cite.title, "cited_text": cite.cited_text})
                                formatted_response += f"(Citation: {cite.title} - {cite.url})"
                return formatted_response

            except Exception as e:
                msg = str(e)
                # Server-side rejections that retrying won't help with: org policy / unsupported tool / auth.
                non_retryable = (
                    "web_search" in msg
                    or "allowedPartnerModelFeatures" in msg
                    or "FAILED_PRECONDITION" in msg
                    or "invalid_request_error" in msg
                    or "401" in msg
                    or "403" in msg
                )
                if non_retryable or attempt >= max_retries:
                    print(
                        f"advanced_web_search_claude: Claude path failed ({type(e).__name__}: {e}); "
                        "falling back to search_google + extract_url_content."
                    )
                    break
                time.sleep(delay)
                delay *= 2

    # Fallback: plain Google search + page scrape. Returns a formatted string so
    # callers that expect text continue to work, just without LLM-summarized citations.
    return _fallback_web_search(query, max_results=max(3, max_searches * 3))


def _fallback_web_search(query: str, max_results: int = 5) -> str:
    """Search the web without an LLM: googlesearch + extract_url_content per hit."""
    print(f"_fallback_web_search: query='{query}', max_results={max_results}")
    try:
        hits = list(search(query, num_results=max_results, lang="en", advanced=True))
    except Exception as e:
        return f"Fallback web search failed at googlesearch step: {type(e).__name__}: {e}"

    if not hits:
        return (
            "Fallback web search returned no results. Google may have soft-blocked this "
            "host's IP. Try again later, reduce frequency, or use a different backend."
        )

    sections: list[str] = []
    for res in hits:
        title = getattr(res, "title", "") or ""
        url = getattr(res, "url", "") or ""
        description = getattr(res, "description", "") or ""
        excerpt = ""
        if url:
            try:
                full = extract_url_content(url)
                excerpt = (full or "")[:2000]
            except Exception as e:
                excerpt = f"(failed to extract page content: {type(e).__name__}: {e})"
        sections.append(
            f"Title: {title}\nURL: {url}\nDescription: {description}\nExcerpt:\n{excerpt}"
        )
    return "\n\n---\n\n".join(sections)


def extract_url_content(url: str) -> str:
    """Extract the text content of a webpage using requests and BeautifulSoup.

    Args:
        url: Webpage URL to extract content from

    Returns:
        Text content of the webpage

    """
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})

    # Check if the response is in text format
    if "text/plain" in response.headers.get("Content-Type", "") or "application/json" in response.headers.get(
        "Content-Type", ""
    ):
        return response.text.strip()  # Return plain text or JSON response directly

    # If it's HTML, use BeautifulSoup to parse
    soup = BeautifulSoup(response.text, "html.parser")

    # Try to find main content first, fallback to body
    content = soup.find("main") or soup.find("article") or soup.body

    # Remove unwanted elements
    for element in content(["script", "style", "nav", "header", "footer", "aside", "iframe"]):
        element.decompose()

    # Extract text with better formatting
    paragraphs = content.find_all(["p", "h1", "h2", "h3", "h4", "h5", "h6"])
    cleaned_text = []

    for p in paragraphs:
        text = p.get_text().strip()
        if text:  # Only add non-empty paragraphs
            cleaned_text.append(text)

    return "\n\n".join(cleaned_text)


def extract_pdf_content(url: str) -> str:
    """Extract the text content of a PDF file given its URL.

    Args:
        url: URL of the PDF file to extract text from

    Returns:
        The extracted text content from the PDF

    """
    try:
        # Check if the URL ends with .pdf
        if not url.lower().endswith(".pdf"):
            # If not, try to find a PDF link on the page
            response = requests.get(url, timeout=30)
            if response.status_code == 200:
                # Look for PDF links in the HTML content
                pdf_links = re.findall(r'href=[\'"]([^\'"]+\.pdf)[\'"]', response.text)
                if pdf_links:
                    # Use the first PDF link found
                    if not pdf_links[0].startswith("http"):
                        # Handle relative URLs
                        base_url = "/".join(url.split("/")[:3])
                        url = base_url + pdf_links[0] if pdf_links[0].startswith("/") else base_url + "/" + pdf_links[0]
                    else:
                        url = pdf_links[0]
                else:
                    return f"No PDF file found at {url}. Please provide a direct link to a PDF file."

        # Download the PDF
        response = requests.get(url, timeout=30)

        # Check if we actually got a PDF file (by checking content type or magic bytes)
        content_type = response.headers.get("Content-Type", "").lower()
        if "application/pdf" not in content_type and not response.content.startswith(b"%PDF"):
            return f"The URL did not return a valid PDF file. Content type: {content_type}"

        pdf_file = BytesIO(response.content)

        # Try with PyPDF2 first
        try:
            text = ""
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            for page_num in range(len(pdf_reader.pages)):
                page = pdf_reader.pages[page_num]
                text += page.extract_text() + "\n\n"
        except Exception as e:
            print(f"Error extracting text from PDF: {str(e)}")

        # Clean up the text
        text = re.sub(r"\s+", " ", text).strip()

        if not text:
            return "The PDF file did not contain any extractable text. It may be an image-based PDF requiring OCR."

        return text

    except requests.exceptions.RequestException as e:
        return f"Error downloading PDF: {str(e)}"
    except Exception as e:
        return f"Error extracting text from PDF: {str(e)}"
