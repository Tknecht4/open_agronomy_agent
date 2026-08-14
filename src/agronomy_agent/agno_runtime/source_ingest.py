from __future__ import annotations

import argparse
import hashlib
import html
import json
import random
import re
import time
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen

from agronomy_agent.paths import repo_path


SKOS = "http://www.w3.org/2004/02/skos/core#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
DOMAIN_ALIASES: dict[str, str] = {
    "markets": "market",
    "agri_business": "market",
    "soil and water": "soil_water",
    "soil_and_water": "soil_water",
    "soil-and-water": "soil_water",
    "soil&water": "soil_water",
    "soil and nutrients": "soil_health",
}


def _canonicalize_knowledge_domain(value: str) -> str:
    normalized = value.strip().lower()
    return DOMAIN_ALIASES.get(normalized, normalized)


def safe_id(value: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")[:70]
    return f"{slug}_{digest}" if slug else digest


class VisibleTextParser(HTMLParser):
    _IGNORED_TAGS = {"script", "style", "noscript", "svg", "nav", "header", "footer", "aside", "form"}

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._IGNORED_TAGS:
            self._skip_depth += 1
        if tag in {"p", "br", "li", "tr", "h1", "h2", "h3", "h4", "section", "article"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._IGNORED_TAGS and self._skip_depth:
            self._skip_depth -= 1
        if tag in {"p", "li", "tr", "h1", "h2", "h3", "h4", "section", "article"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = " ".join(data.split())
        if text:
            self.parts.append(text)

    def text(self) -> str:
        raw = " ".join(self.parts)
        raw = re.sub(r"\s*\n\s*", "\n", raw)
        raw = re.sub(r"[ \t]{2,}", " ", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def clean_text(text: str, source_domain: str = "") -> str:
    text = text.replace("\x00", " ")
    text = text.replace("\u00ad", "")
    text = text.replace("\u00a0", " ")
    normalized_domain = str(source_domain).lower().replace("www.", "")
    noisy_markers = (
        "search",
        "forum list",
        "jump to forum",
        "menu",
        "new posts",
        "unread posts",
        "home",
        "forums",
        "footer links",
        "printer friendly",
        "log in",
        "register",
        "you are logged in as a guest",
        "please log in or register to reply",
        "install the app",
        "toggle sidebar",
        "share this page",
        "share:",
        "track",
        "you are using an out of date browser",
        "tracking tools",
    )
    hard_boilerplate = (
        "follow along with the video below to see how to install our site as a web app on your home screen",
        "note: this feature may not be available in some browsers",
        "note: this feature may not be available in some browsers.",
        "featured topics",
        "need help? whatsapp us at",
        "get daily agriculture business leads on whatsapp",
        "please log in or register to reply here",
        "please add to the discussion here",
        "please do read the forum rules before posting",
        "you can read more on",
        "by continuing to use this site",
        "this website uses tracking tools",
        "you are using an out of date browser",
        "you should upgrade or use an alternative browser",
        "title: opt out of the sale or sharing of personal information",
        "title: log in",
        "continue as a guest",
        "by clicking i agree",
        "you agree to our [privacy policy]",
        "you should upgrade or use an alternative browser.",
        "you are logged in as a guest",
        "e-mail a link to this thread",
        "filter",
        "today's posts",
        "back top",
        "people",
        "member profiles and intros",
        "new member",
        "members online",
        "thread starter",
        "thread starter?",
        "return to topic list",
        "previous template next",
        "reply to this thread",
        "post cancel",
        "start date",
        "view previous thread",
        "view next thread",
        "member profiles and intros",
        "members online",
        "no members online now",
        "new member",
        "thread list",
        "back top",
        "new and popular",
        "agric info policy",
        "business, marketing, and economics",
        "apply for free",
        "you will need to login or register before you can post a message",
        "a apply for free",
        "please register",
        "working... ok ok cancel",
        "click to expand",
        "view attachment",
        "delete cookies",
        "( delete cookies )",
        "whichwire",
        "track/click",
        "tags:",
        "join date:",
        "posts:",
        "welcome to farmnest agriculture forum!",
        "forum4farming",
        "agriville.com",
        "farmchat.com",
        "classifieds",
        "agriculture",
        "machinery",
        "crops",
        "livestock",
    )
    agrictalk_boilerplate = (
        "sell on agrictalk",
        "agri biz companies",
        "agribiz companies",
        "agribiz",
        "agricultalk_ai",
        "article gallery",
        "article gallery discussion",
        "submit suggestions to help improve this platform and win n100k if we implement your idea.",
        "cows / cattle",
        "import & export",
        "fish farming",
        "poultry farming",
        "farm equipment",
        "facebook x linkedin reddit whatsapp email share link",
        "₦1 million potato",
        "agritech ai",
        "agric talk",
        "agricollege",
        "agricultalk",
    )
    text = re.sub(r"([a-z])-\s+([a-z])", r"\1\2", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    cleaned_lines: list[str] = []
    for line in text.splitlines():
        normalized = line.strip().lower()
        if not line.strip():
            continue
        if re.search(r"\[/?url\]", normalized):
            continue
        if re.fullmatch(r"#\d+", normalized):
            continue
        if len(line.split()) <= 1 and normalized in {"agriculture", "machinery", "crops", "livestock", "classifieds"}:
            continue
        if any(marker in normalized for marker in hard_boilerplate):
            continue
        if normalized_domain.endswith("agrictalk.com") and any(marker in normalized for marker in agrictalk_boilerplate):
            continue
        if len(line.split()) <= 3 and ("top" in normalized or "member" in normalized or "new" in normalized):
            if any(marker in normalized for marker in ("top", "member", "new", "filter")):
                continue
        if any(marker in normalized for marker in noisy_markers) and len(line.split()) <= 24:
            continue
        if re.match(r"^(start date|thread starter|members online|new member|message[s]?$)", normalized):
            continue
        if any(marker in normalized for marker in ("featured topics", "media gallery", "forum list", "news & articles")) and len(line.split()) <= 12:
            continue
        cleaned_lines.append(line.strip())
    deduped_lines: list[str] = []
    for line in cleaned_lines:
        if deduped_lines and line.lower() == deduped_lines[-1].lower():
            continue
        deduped_lines.append(line)
    return "\n".join(deduped_lines).strip()


def _jina_proxy_url(url: str) -> str:
    parsed = urlparse(url)
    source = f"{parsed.netloc}{parsed.path}"
    if parsed.query:
        source = f"{source}?{parsed.query}"
    return f"https://r.jina.ai/http://{source}"


def _is_fallback_blocked_content(html_doc: str) -> bool:
    marker = html_doc.lower()
    blocked_markers = (
        "warning: target url returned error",
        "title: log in",
        "title: opt out of the sale or sharing of personal information",
        "you are currently not logged in",
    )
    return any(m in marker for m in blocked_markers)


def fetch_with_fallback(
    url: str,
    source: dict[str, Any],
    timeout: int = 60,
    *,
    delay_seconds: float = 0.0,
    request_jitter_seconds: float = 0.0,
    max_retries: int = 3,
) -> str:
    host = urlparse(url).netloc.lower()
    fallback_host = any(domain in host for domain in ("agriville.com", "forum4farming.com", "agriforum"))
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            return fetch_url(
                url,
                timeout=timeout,
                delay_seconds=delay_seconds,
                request_jitter_seconds=request_jitter_seconds,
                max_retries=1,
            )
        except (HTTPError, URLError, OSError, TimeoutError) as exc:
            last_exc = exc
            if attempt + 1 < max_retries:
                continue
            if not fallback_host:
                break
            try:
                proxy_html = fetch_url(
                    _jina_proxy_url(url),
                    timeout=min(timeout, 45),
                    delay_seconds=delay_seconds,
                    request_jitter_seconds=request_jitter_seconds,
                    max_retries=1,
                )
                if _is_fallback_blocked_content(proxy_html):
                    break
                return proxy_html
            except Exception:
                break
    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"unable to fetch {url}")


def _find_links_from_html(raw_html: str, base_url: str, *, keep_query: bool = True) -> list[str]:
    raw_links = re.findall(r'href=[\"\']([^\"\']+)', raw_html, flags=re.IGNORECASE)
    links: list[str] = []
    for raw in raw_links:
        normalized = html.unescape(raw).split("#")[0].strip()
        if not normalized:
            continue
        if not keep_query:
            normalized = normalized.split("?")[0]
        links.append(urljoin(base_url, normalized))
    return links


def _is_seed_page_url(source: dict[str, Any], raw_url: str) -> bool:
    source_host = urlparse(source["url"]).netloc.lower()
    parsed = urlparse(raw_url)
    if not parsed.netloc or parsed.netloc.lower() != source_host:
        return False
    normalized = f"{parsed.path.lower()}{'?' + parsed.query.lower() if parsed.query else ''}"
    if "thread-view.asp" in normalized or "/threads/" in normalized or "/thread/" in normalized or "/post-" in normalized:
        return False
    if ".rss" in normalized or ".xml" in normalized or "feed" in normalized:
        return False
    if any(keyword in normalized for keyword in ("login", "register", "search", "user", "logout", "sign-in", "sign-up")):
        return False
    return "/forums/" in normalized or "/forum/" in normalized or "/page-" in normalized or "page=" in normalized


def _discover_seed_urls_from_html(source: dict[str, Any], raw_html: str, base_url: str, *, max_urls: int | None = None) -> list[str]:
    discovered: list[str] = []
    seed_links_regex = source.get("seed_page_link_regex")
    compiled_seed_links_re = re.compile(seed_links_regex, re.IGNORECASE) if seed_links_regex else None
    for full in _find_links_from_html(raw_html, base_url):
        if not _is_seed_page_url(source, full):
            continue
        if compiled_seed_links_re is not None and not compiled_seed_links_re.search(full):
            continue
        discovered.append(full)
        if max_urls is not None and len(discovered) >= max_urls:
            break
    deduped: list[str] = []
    seen = set()
    for value in discovered:
        if value not in seen:
            deduped.append(value)
            seen.add(value)
    return deduped


def chunk_text(text: str, max_words: int, overlap_words: int) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_words = 0
    for paragraph in paragraphs:
        words = paragraph.split()
        if len(words) > max_words:
            if current:
                chunks.append(" ".join(current).strip())
                current, current_words = [], 0
            step = max_words - overlap_words
            if step <= 0:
                step = max(1, max_words // 2)
            for i in range(0, len(words), step):
                piece = words[i : i + max_words]
                if len(piece) >= 40:
                    chunks.append(" ".join(piece).strip())
            continue
        if current_words + len(words) > max_words and current:
            chunks.append(" ".join(current).strip())
            tail = " ".join(current).split()[-overlap_words:] if overlap_words else []
            current = [" ".join(tail)] if tail else []
            current_words = len(tail)
        current.append(paragraph)
        current_words += len(words)
    if current:
        chunks.append(" ".join(current).strip())
    return [chunk for chunk in chunks if len(chunk.split()) >= 40]


def canonical_thread_url(source: dict[str, Any], raw_url: str) -> str:
    try:
        parsed = urlparse(raw_url)
        host = parsed.netloc.lower()
        path = parsed.path
        query_pairs = dict(parse_qsl(parsed.query, keep_blank_values=True))
        if "newagtalk.com" in host and path.endswith("thread-view.asp"):
            thread_id = query_pairs.get("tid", "")
            if thread_id:
                return urlunparse((parsed.scheme, parsed.netloc, path, "", urlencode({"tid": thread_id}), ""))
        if "agrictalk.com" in host and path.startswith("/threads/"):
            if "/post-" in path:
                path = path.split("/post-")[0]
            return urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))
        if "farmchat.com" in host and path.startswith("/threads/"):
            path = path.split("/post-")[0]
            path = path.rstrip("/")
            path = re.sub(r"/latest$", "", path, flags=re.IGNORECASE)
            path = re.sub(r"/page-\d+$", "", path, flags=re.IGNORECASE)
            return urlunparse((parsed.scheme, parsed.netloc, path.rstrip("/"), "", "", ""))
        if "agriville.com" in host:
            if parsed.query:
                query_pairs = dict(parse_qsl(parsed.query, keep_blank_values=True))
                query_pairs.pop("p", None)
            return urlunparse((parsed.scheme, parsed.netloc, path.rstrip("/"), "", "", ""))
        if "agricultureinformation.com" in host and "/forums/threads/" in path:
            path = re.sub(r"/post-\d+/?$", "", path)
            path = re.sub(r"/latest/?$", "", path)
            return urlunparse((parsed.scheme, parsed.netloc, path.rstrip("/"), "", "", ""))
        if "forum4farming.com" in host and path.startswith("/forum/index.php"):
            query = parsed.query
            if query.startswith("threads/"):
                query = re.sub(r"/post-\d+/?$", "", query)
                query = re.sub(r"/page-\d+/?$", "", query)
                return urlunparse((parsed.scheme, parsed.netloc, path, "", query, ""))
        if "soilforwater.org" in host and "/threads/" in path:
            path = re.sub(r"/post-\d+/?$", "", path)
            return urlunparse((parsed.scheme, parsed.netloc, path.rstrip("/"), "", "", ""))
    except Exception:
        return raw_url
    return raw_url


def _to_domain_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        normalized = _canonicalize_knowledge_domain(value)
        return [normalized] if normalized else []
    out = [_canonicalize_knowledge_domain(str(item)) for item in value]
    return sorted({item for item in out if item})


def _to_int(value: Any, fallback: int) -> int:
    try:
        as_int = int(value)
        return as_int if as_int > 0 else fallback
    except (TypeError, ValueError):
        return fallback


def fetch_url(
    url: str,
    timeout: int = 60,
    *,
    delay_seconds: float = 0.0,
    request_jitter_seconds: float = 0.0,
    max_retries: int = 3,
) -> str:
    if delay_seconds > 0:
        time.sleep(delay_seconds)
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            if request_jitter_seconds > 0:
                time.sleep(random.uniform(0.0, request_jitter_seconds))
            req = Request(
                url,
                headers={
                    "User-Agent": "agronomy-agent-corpus-builder/0.1",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
            )
            with urlopen(req, timeout=timeout) as response:
                return response.read().decode("utf-8", errors="ignore")
        except HTTPError as exc:
            last_exc = exc
            if exc.code in {429, 500, 502, 503, 504} and attempt + 1 < max_retries:
                wait_seconds = min(8.0, 1.5 * (2**attempt))
                time.sleep(wait_seconds)
                continue
            raise
        except (URLError, OSError, TimeoutError) as exc:
            last_exc = exc
            if attempt + 1 < max_retries:
                wait_seconds = min(6.0, 1.0 * (2**attempt))
                time.sleep(wait_seconds)
                continue
            raise
    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"failed fetching {url}")


def extract_links_from_html(source: dict[str, Any], raw_html: str, base_url: str) -> list[str]:
    pattern = source.get("thread_link_regex", r"/thread-view\.asp\?[^\"'\s>]+")
    compiled = re.compile(pattern, re.IGNORECASE)
    raw_links = re.findall(r'href=[\"\']([^\"\']+)', raw_html, flags=re.IGNORECASE)
    links: list[str] = []
    for raw in raw_links:
        if not compiled.search(raw):
            continue
        normalized = html.unescape(raw).split("#")[0]
        normalized = normalized.split("?start=")[0].split("&start=")[0]
        normalized = canonical_thread_url(source, urljoin(base_url, normalized))
        if "reddit.com" in normalized:
            continue
        links.append(normalized)
    # Preserve order while deduplicating.
    seen = set()
    ordered: list[str] = []
    for link in links:
        if link not in seen:
            ordered.append(link)
            seen.add(link)
    if not ordered and source.get("thread_urls"):
        for raw in source["thread_urls"]:
            ordered.append(canonical_thread_url(source, raw))
    if source.get("max_threads") and source["max_threads"] > 0:
        ordered = ordered[: int(source["max_threads"])]
    return ordered


def _record_link_discovery_failure(
    diagnostics: list[dict[str, str]] | None,
    *,
    stage: str,
    url: str,
    exc: Exception,
) -> None:
    if diagnostics is None:
        return
    diagnostics.append(
        {
            "stage": stage,
            "url": url,
            "error_type": type(exc).__name__,
            "error": str(exc)[:240],
        }
    )


def _feed_fetch_failure_count(diagnostics: list[dict[str, str]]) -> int:
    return sum(1 for row in diagnostics if row.get("stage") in {"feed_fetch", "feed_proxy_fetch"})


def _extract_feed_thread_links(
    feed_url: str,
    source: dict[str, Any],
    fetch_timeout_seconds: int,
    *,
    diagnostics: list[dict[str, str]] | None = None,
) -> list[str]:
    parsed_pattern = re.compile(source.get("thread_link_regex", r"/thread-view\\.asp\\?[^\"'\\s>]+"), re.IGNORECASE)

    def _normalize_feed_text(raw_text: str) -> list[str]:
        text = raw_text.strip()
        ordered: list[str] = []
        seen = set()
        if text.startswith("<") and ("<rss" in text[:120].lower() or "<feed" in text[:120].lower()):
            try:
                root = ET.fromstring(text)
            except Exception:
                root = None
            if root is not None:
                links: list[str] = []
                for link_node in root.findall(".//{*}item/{*}link"):
                    if link_node.text:
                        links.append(link_node.text.strip())
                for link_node in root.findall(".//{*}entry/{*}link"):
                    href = link_node.attrib.get("href")
                    if href:
                        links.append(href.strip())
                for raw_link in links:
                    normalized = canonical_thread_url(source, raw_link.split("#")[0])
                    if not parsed_pattern.search(normalized):
                        continue
                    if normalized in seen:
                        continue
                    ordered.append(normalized)
                    seen.add(normalized)
                if ordered:
                    return ordered
        for href in _find_links_from_html(raw_text, feed_url):
            normalized = canonical_thread_url(source, href.split("#")[0])
            if not parsed_pattern.search(normalized):
                continue
            if normalized in seen:
                continue
            ordered.append(normalized)
            seen.add(normalized)
        if not ordered:
            for fallback_link in re.findall(r"https?://[^\"'\\s<>]+", raw_text, flags=re.IGNORECASE):
                normalized = canonical_thread_url(source, fallback_link.split("#")[0])
                if not parsed_pattern.search(normalized):
                    continue
                if normalized in seen:
                    continue
                ordered.append(normalized)
                seen.add(normalized)
        return ordered

    try:
        raw_feed = fetch_url(feed_url, timeout=fetch_timeout_seconds, max_retries=2)
    except Exception as exc:
        _record_link_discovery_failure(diagnostics, stage="feed_fetch", url=feed_url, exc=exc)
        return []

    links = _normalize_feed_text(raw_feed)
    if links:
        return links

    host = urlparse(feed_url).netloc.lower()
    fallback_host = any(domain in host for domain in ("agriville.com", "forum4farming.com", "agriforum"))
    if fallback_host:
        try:
            proxy_feed = fetch_url(_jina_proxy_url(feed_url), timeout=min(fetch_timeout_seconds, 45), max_retries=2)
        except Exception as exc:
            _record_link_discovery_failure(diagnostics, stage="feed_proxy_fetch", url=feed_url, exc=exc)
            return []
        return _normalize_feed_text(proxy_feed)

    return []


def _discover_seed_rss_urls(source: dict[str, Any], seed_html: str, base_url: str) -> list[str]:
    discovered: list[str] = []
    for item in source.get("seed_rss_urls", []):
        discovered.append(item)
    feed_pattern = re.compile(
        r"<link[^>]+type=[\"']application/(?:rss\\+xml|atom\\+xml)[\"'][^>]+href=[\"']([^\"']+)",
        re.IGNORECASE,
    )
    for match in feed_pattern.finditer(seed_html):
        discovered.append(html.unescape(match.group(1)))
    feed_href_pattern = re.compile(r"<(?:link|a)[^>]+href=[\"']([^\"']+)", re.IGNORECASE)
    for match in feed_href_pattern.finditer(seed_html):
        href = html.unescape(match.group(1))
        lower = href.lower()
        if ".rss" not in lower and ".xml" not in lower and "feed" not in lower:
            continue
        discovered.append(href)
    if not discovered:
        return []
    links = []
    for raw in discovered:
        full = urljoin(base_url, raw).split("#")[0]
        if not full.startswith("http://") and not full.startswith("https://"):
            continue
        links.append(full)
    return sorted(set(links))


def extract_links_from_seed(
    source: dict[str, Any],
    raw_html: str,
    base_url: str,
    fetch_timeout_seconds: int,
    *,
    diagnostics: list[dict[str, str]] | None = None,
) -> list[str]:
    thread_urls = extract_links_from_html(source, raw_html, base_url)
    feed_urls = _discover_seed_rss_urls(source, raw_html, base_url)
    if not feed_urls:
        return thread_urls
    for feed_url in feed_urls:
        for link in _extract_feed_thread_links(feed_url, source, fetch_timeout_seconds, diagnostics=diagnostics):
            if link not in thread_urls:
                thread_urls.append(link)
    seen = set()
    ordered = []
    for link in thread_urls:
        if link in seen:
            continue
        ordered.append(link)
        seen.add(link)
    return ordered


def parse_title(html_doc: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html_doc, flags=re.I | re.S)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    return ""


def html_to_text(html_doc: str) -> str:
    parser = VisibleTextParser()
    parser.feed(html_doc)
    return parser.text()


def extract_forum_threads(source: dict[str, Any], raw_html: str, base_url: str, *, fetch_timeout_seconds: int = 60) -> tuple[
    list[dict[str, str]], dict[str, Any]
]:
    thread_urls: list[str] = []
    link_discovery_failures: list[dict[str, str]] = []
    max_seed_pages = _to_int(source.get("max_seed_pages", 14), 14)
    max_seed_urls_per_page = _to_int(source.get("max_seed_urls", 40), 40)
    seen_seed_urls = set()
    seed_urls: list[str] = [base_url]
    seed_urls.extend([seed for seed in source.get("seed_urls", []) if isinstance(seed, str)])
    seed_urls.extend(_discover_seed_urls_from_html(source, raw_html, base_url, max_urls=max_seed_urls_per_page))
    seen_seed_urls.update(seed_urls)
    index = 0
    while index < len(seed_urls) and index < max_seed_pages:
        seed_url = seed_urls[index]
        if seed_url == base_url:
            seed_html = raw_html
        else:
            try:
                seed_html = fetch_with_fallback(
                    seed_url,
                    source,
                    timeout=fetch_timeout_seconds,
                    delay_seconds=0.0,
                    request_jitter_seconds=0.0,
                    max_retries=_to_int(source.get("fetch_retries", 3), 3),
                )
            except (HTTPError, URLError, TimeoutError, OSError) as exc:
                print(f"{source['id']}: failed seed fetch {seed_url}: {exc!r}")
                index += 1
                continue
        thread_urls.extend(
            extract_links_from_seed(
                source,
                seed_html,
                seed_url,
                fetch_timeout_seconds,
                diagnostics=link_discovery_failures,
            )
        )
        discovered_seed_urls = _discover_seed_urls_from_html(
            source,
            seed_html,
            seed_url,
            max_urls=max_seed_urls_per_page,
        )
        for discovered in discovered_seed_urls:
            if discovered not in seen_seed_urls:
                seed_urls.append(discovered)
                seen_seed_urls.add(discovered)
                if len(seed_urls) >= max_seed_pages:
                    break
        if len(seed_urls) >= max_seed_pages:
            break
        index += 1

    if not thread_urls:
        return [], {
            "discovered_threads": 0,
            "successful_threads": 0,
            "failed_threads": 0,
            "feed_fetch_failures": _feed_fetch_failure_count(link_discovery_failures),
            "link_discovery_failure_count": len(link_discovery_failures),
            "link_discovery_failures": link_discovery_failures[:10],
        }

    deduped_thread_urls: list[str] = []
    seen_urls = set()
    for thread_url in thread_urls:
        if thread_url in seen_urls:
            continue
        deduped_thread_urls.append(thread_url)
        seen_urls.add(thread_url)
    max_threads = _to_int(source.get("max_threads", 0), 0)
    if max_threads > 0:
        deduped_thread_urls = deduped_thread_urls[:max_threads]
    thread_urls = deduped_thread_urls

    rows: list[dict[str, str]] = []

    max_words = int(source.get("max_words", 260))
    overlap_words = int(source.get("overlap_words", 30))
    tags = list(source.get("tags", ["forum", "community"]))
    base_source_type = source.get("source_type", "community_forum")
    allowed_roles = list(source.get("allowed_roles", ["farmer", "crop_adviser"]))
    allowed_roles = sorted({str(value).strip().lower() for value in allowed_roles if str(value).strip()})
    knowledge_domains = _to_domain_list(source.get("knowledge_domains"))
    knowledge_bucket = str(source.get("knowledge_bucket", "farmer_knowledge")).strip().lower() or "farmer_knowledge"
    if knowledge_bucket and knowledge_bucket not in knowledge_domains:
        knowledge_domains = sorted({knowledge_bucket, *knowledge_domains})
    thread_delay = float(source.get("thread_delay_seconds", source.get("crawl_delay_seconds", 0.0)) or 0.0)
    thread_fetch_delay = max(0.0, thread_delay)
    thread_fetch_failures = 0
    thread_fetch_success = 0

    for thread_url in thread_urls:
        thread_jitter = float(source.get("thread_jitter_seconds", source.get("crawl_jitter_seconds", 0.0)) or 0.0)
        try:
            thread_html = fetch_with_fallback(
                thread_url,
                source,
                timeout=fetch_timeout_seconds,
                delay_seconds=thread_fetch_delay,
                request_jitter_seconds=thread_jitter,
                max_retries=_to_int(source.get("fetch_retries", 3), 3),
            )
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            print(f"{source['id']}: failed thread fetch {thread_url}: {exc!r}")
            thread_fetch_failures += 1
            continue
        thread_fetch_success += 1
        title = parse_title(thread_html)
        text = clean_text(html_to_text(thread_html), source_domain=urlparse(thread_url).netloc)
        chunks = chunk_text(text, max_words=max_words, overlap_words=overlap_words)
        for chunk_idx, chunk in enumerate(chunks, start=1):
            if len(chunk.split()) < 40:
                continue
            rows.append(
                {
                    "doc_id": f"{source['id']}_{safe_id(thread_url)}_{chunk_idx:03d}",
                    "title": title,
                    "text": chunk,
                    "source": thread_url,
                    "source_id": source["id"],
                    "source_type": base_source_type,
                    "source_domain": urlparse(thread_url).netloc,
                    "license": source.get("license", "public_forum"),
                    "tags": tags,
                    "knowledge_bucket": knowledge_bucket,
                    "knowledge_domains": knowledge_domains,
                    "allowed_roles": allowed_roles,
                }
            )
    summary = {
        "discovered_threads": len(thread_urls),
        "successful_threads": thread_fetch_success,
        "failed_threads": thread_fetch_failures,
        "feed_fetch_failures": _feed_fetch_failure_count(link_discovery_failures),
        "link_discovery_failure_count": len(link_discovery_failures),
        "link_discovery_failures": link_discovery_failures[:10],
    }
    return rows, summary


def ingest_forum(source: dict[str, Any], raw_dir: Path, out_dir: Path, force: bool = False) -> dict:
    del raw_dir  # Reserved for future per-thread cache expansion.
    del force
    source_url = source["url"]
    source_delay = float(source.get("seed_delay_seconds", source.get("crawl_delay_seconds", 0.0)) or 0.0)
    source_jitter = float(source.get("seed_jitter_seconds", source.get("crawl_jitter_seconds", 0.0)) or 0.0)
    fetch_timeout_seconds = _to_int(source.get("fetch_timeout_seconds"), 60)
    thread_seed_html = fetch_with_fallback(
        source_url,
        source,
        timeout=fetch_timeout_seconds,
        delay_seconds=source_delay,
        request_jitter_seconds=source_jitter,
        max_retries=_to_int(source.get("fetch_retries", 3), 3),
    )
    rows, thread_stats = extract_forum_threads(
        source,
        thread_seed_html,
        source_url,
        fetch_timeout_seconds=fetch_timeout_seconds,
    )
    output = out_dir / f"{source['id']}_forum_threads_rag_corpus.jsonl"
    if output.exists():
        output.unlink()
    write_jsonl(output, rows)
    return {
        "source_id": source["id"],
        "source_name": source.get("name", source["id"]),
        "forum_urls": rows[:2],
        "chunks": len(rows),
        "threads": thread_stats["successful_threads"],
        "discovered_threads": thread_stats["discovered_threads"],
        "failed_threads": thread_stats["failed_threads"],
        "feed_fetch_failures": thread_stats.get("feed_fetch_failures", 0),
        "link_discovery_failure_count": thread_stats.get("link_discovery_failure_count", 0),
        "link_discovery_failures": thread_stats.get("link_discovery_failures", []),
        "corpus": str(output),
    }


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def best_literal(graph, subject, predicates: list[object]) -> str:
    for pred in predicates:
        values = list(graph.objects(subject, pred))
        if not values:
            continue
        english = [str(v) for v in values if getattr(v, "language", None) in (None, "en")]
        if english:
            return english[0]
        return str(values[0])
    return ""


def literals(graph, subject, predicate: object) -> list[str]:
    vals = []
    for value in graph.objects(subject, predicate):
        if getattr(value, "language", None) in (None, "en"):
            vals.append(str(value))
    return vals


def compact_uri(uri: object) -> str:
    text = str(uri)
    if "#" in text:
        return text.rsplit("#", 1)[-1]
    return text.rstrip("/").rsplit("/", 1)[-1]


def download(url: str, output: Path, force: bool = False) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and not force:
        return output
    with urlopen(url, timeout=60) as response:
        output.write_bytes(response.read())
    return output


def ingest_soilwise(source: dict, raw_dir: Path, out_dir: Path, force: bool = False) -> dict:
    from rdflib import Graph, RDF, URIRef

    ttl = download(source["url"], raw_dir / "soilwise_soil_health_KG.ttl", force=force)
    graph = Graph()
    graph.parse(str(ttl), format="turtle")
    concept_type = URIRef(SKOS + "Concept")
    pref = URIRef(SKOS + "prefLabel")
    alt = URIRef(SKOS + "altLabel")
    definition = URIRef(SKOS + "definition")
    exact = URIRef(SKOS + "exactMatch")
    broader = URIRef(SKOS + "broader")
    narrower = URIRef(SKOS + "narrower")
    related = URIRef(SKOS + "related")
    label = URIRef(RDFS + "label")

    uri_to_id: dict[str, str] = {}
    docs: list[dict] = []
    nodes: list[dict] = []
    for subject in sorted(set(graph.subjects(RDF.type, concept_type)), key=str):
        name = best_literal(graph, subject, [pref, label])
        if not name:
            continue
        uri = str(subject)
        node_id = "soilwise_" + safe_id(uri)
        uri_to_id[uri] = node_id
        aliases = literals(graph, subject, alt)
        definitions = literals(graph, subject, definition)
        external = [compact_uri(v) for v in graph.objects(subject, exact)]
        text_bits = [name]
        if aliases:
            text_bits.append("Aliases: " + ", ".join(aliases[:8]))
        if definitions:
            text_bits.append("Definition: " + definitions[0])
        if external:
            text_bits.append("External vocabulary links: " + ", ".join(external[:8]))
        text = ". ".join(bit.strip(". ") for bit in text_bits if bit)
        docs.append(
            {
                "doc_id": node_id,
                "title": f"Soil health concept: {name}",
                "text": text,
                "source": source["record_url"],
                "license": source["license"],
                "tags": ["soil health", "soilwise", "knowledge graph"],
            }
        )
        nodes.append(
            {
                "id": node_id,
                "name": name,
                "kind": "soil health concept",
                "description": definitions[0] if definitions else text,
                "aliases": aliases[:12],
                "source": source["record_url"],
                "license": source["license"],
            }
        )

    edges: list[dict] = []
    edge_preds = [(broader, "broader"), (narrower, "narrower"), (related, "related_to"), (exact, "exact_match")]
    for subject_uri, source_id in uri_to_id.items():
        subject = URIRef(subject_uri)
        for pred, relation in edge_preds:
            for obj in graph.objects(subject, pred):
                target_id = uri_to_id.get(str(obj))
                if target_id:
                    edges.append({"source": source_id, "target": target_id, "relation": relation})

    write_jsonl(out_dir / "soilwise_rag_corpus.jsonl", docs)
    graph_path = out_dir / "soilwise_knowledge_graph.json"
    graph_path.write_text(
        json.dumps({"nodes": nodes, "edges": edges}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    graph_sha256 = hashlib.sha256(graph_path.read_bytes()).hexdigest()
    graph_manifest_path = out_dir / "soilwise_knowledge_graph.manifest.json"
    graph_manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "open_agronomy_agent.knowledge_graph_manifest.v1",
                "graph_id": "soilwise.soil_health",
                "version": f"15593868+{graph_sha256[:12]}",
                "data_path": graph_path.name,
                "namespaces": ["fertility", "regional_environment", "soil_health", "soil_water"],
                "source": source["record_url"],
                "license": source["license"],
                "sha256": graph_sha256,
                "authority_role": "vocabulary_hint",
                "priority": 50,
                "collision_policy": "error",
                "relation_vocabulary": ["broader", "exact_match", "narrower", "related_to"],
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    summary = {
        "source_id": source["id"],
        "raw_ttl": str(ttl),
        "triples": len(graph),
        "docs": len(docs),
        "nodes": len(nodes),
        "edges": len(edges),
        "corpus": str(out_dir / "soilwise_rag_corpus.jsonl"),
        "graph": str(graph_path),
        "graph_manifest": str(graph_manifest_path),
    }
    return summary


def run_single_source(source: dict[str, Any], output_dir: Path, raw_dir: Path, force: bool) -> dict[str, Any]:
    source_kind = source["kind"]
    if source_kind == "rdf_kg":
        return ingest_soilwise(source, raw_dir, output_dir, force=force)
    if source_kind == "forum_board":
        return ingest_forum(source, raw_dir, output_dir, force=force)
    raise ValueError(f"unsupported source kind: {source_kind}")


def run_sources(
    manifest_path: Path,
    output_dir: Path,
    raw_dir: Path,
    source_ids: list[str] | None = None,
    source_kind: str | None = None,
    force: bool = False,
    inter_source_delay_seconds: float | None = None,
    inter_source_jitter_seconds: float | None = None,
    max_sources: int | None = None,
) -> list[dict[str, Any]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sources = manifest.get("sources", [])
    if not isinstance(sources, list):
        raise ValueError("invalid manifest: expected sources list")

    selected: list[dict[str, Any]] = []
    if source_ids:
        source_index = {item["id"]: item for item in sources if "id" in item}
        for source_id in source_ids:
            if source_id not in source_index:
                raise ValueError(f"source id not found in manifest: {source_id}")
            source = source_index[source_id]
            if source_kind and source.get("kind") != source_kind:
                continue
            selected.append(source)
    elif source_kind:
        selected = [item for item in sources if item.get("kind") == source_kind]
    elif sources:
        selected = [sources[0] if sources else {}]
    if not selected:
        raise ValueError("no sources selected for ingestion")
    if max_sources is not None and max_sources > 0:
        selected = selected[:max_sources]

    results: list[dict[str, Any]] = []
    for index, source in enumerate(selected):
        if index > 0:
            if inter_source_delay_seconds is None:
                source_delay = float(
                    source.get(
                        "inter_source_delay_seconds",
                        source.get("seed_delay_seconds", source.get("crawl_delay_seconds", 0.0)),
                    )
                    or 0.0
                )
            else:
                source_delay = float(inter_source_delay_seconds)
            if inter_source_jitter_seconds is None:
                source_jitter = float(
                    source.get(
                        "inter_source_jitter_seconds",
                        source.get("seed_jitter_seconds", source.get("crawl_jitter_seconds", 0.0)),
                    )
                    or 0.0
                )
            else:
                source_jitter = float(inter_source_jitter_seconds)
            source_delay = max(0.0, source_delay)
            source_jitter = max(0.0, source_jitter)
            if source_delay > 0:
                time.sleep(source_delay + random.uniform(0.0, source_jitter))
        results.append(run_single_source(source, output_dir, raw_dir, force=force))
    return results


def _default_source_id() -> list[str]:
    return ["forum_newagtalk", "forum_agricultivation_communities_agrictalk"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest public RAG/KG sources into ignored derived artifacts.")
    parser.add_argument("--manifest", default="data/manifests/rag_sources.json")
    parser.add_argument("--output-dir", default="data/derived/rag")
    parser.add_argument("--raw-dir", default="data/raw/rag")
    parser.add_argument("--source-id", action="append")
    parser.add_argument("--source-kind", dest="source_kind")
    parser.add_argument("--inter-source-delay", type=float, default=2.0)
    parser.add_argument("--inter-source-jitter", type=float, default=0.75)
    parser.add_argument("--max-sources", type=int, default=None)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(args=argv)

    output_dir = repo_path(args.output_dir)
    raw_dir = repo_path(args.raw_dir)
    manifest_path = repo_path(args.manifest)
    source_kind = args.source_kind
    if not args.source_id and source_kind is None:
        source_kind = "forum_board"
    if args.source_id is not None:
        source_ids = args.source_id
    elif source_kind is None:
        source_ids = _default_source_id()
    else:
        source_ids = None

    summaries = run_sources(
        manifest_path=manifest_path,
        output_dir=output_dir,
        raw_dir=raw_dir,
        source_ids=source_ids,
        source_kind=source_kind,
        force=args.force,
        inter_source_delay_seconds=args.inter_source_delay,
        inter_source_jitter_seconds=args.inter_source_jitter,
        max_sources=args.max_sources,
    )
    out = output_dir / "ingest_summary.json"
    if len(summaries) == 1:
        out.write_text(json.dumps(summaries[0], indent=2), encoding="utf-8")
        print(json.dumps(summaries[0], indent=2))
    else:
        out.write_text(json.dumps(summaries, indent=2), encoding="utf-8")
        print(json.dumps(summaries, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
