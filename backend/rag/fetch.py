"""
Polite fetching + text extraction for official advisory pages and PDFs.

- Identifies itself honestly (USER_AGENT) and never rotates or spoofs agents.
- Respects robots.txt (RFC 9309). A 401/403 on robots.txt is treated as
  "disallow all" (conservative); other 4xx means "no rules"; 5xx / network
  errors mean "disallow" for this run.
- One request per second per host.
- Raw bytes are cached in rag/raw/ so re-runs (and ingestion on another
  machine) do not hit the sites again.
"""

import hashlib
import json
import os
import re
import time
import logging
import urllib.parse
import urllib.robotparser
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("moneytrace.rag.fetch")

USER_AGENT = os.environ.get(
    "RAG_USER_AGENT",
    "MoneyTraceBot/1.0 (student fraud-awareness project; +https://github.com/hannielvinu/MoneyTrace)",
)
RAW_DIR = os.path.join(os.path.dirname(__file__), "raw")
MIN_INTERVAL_S = float(os.environ.get("RAG_MIN_INTERVAL_S", "1.0"))


@dataclass
class FetchResult:
    url: str
    ok: bool
    status: Optional[int] = None
    content_type: str = ""
    body: bytes = b""
    error: str = ""
    from_cache: bool = False
    final_url: str = ""


def is_bot_challenge(body: bytes) -> bool:
    head = body[:4000]
    return b"TSPD" in head or b'window["bobcmn"]' in head or b"cf-chl" in head or b"captcha" in head.lower()


@dataclass
class ExtractedDoc:
    title: str
    text: str                      # markdown-ish: headings kept as "# ..." lines
    language: str = "en"
    published_date: Optional[str] = None
    sections: List[str] = field(default_factory=list)


def _cache_paths(url: str) -> Tuple[str, str]:
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return os.path.join(RAW_DIR, h + ".bin"), os.path.join(RAW_DIR, h + ".json")


class PoliteFetcher:
    def __init__(self, timeout: float = 45.0, use_cache: bool = True):
        self.client = httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT})
        self.use_cache = use_cache
        self._robots: Dict[str, Optional[urllib.robotparser.RobotFileParser]] = {}
        self._robots_status: Dict[str, str] = {}
        self._last_hit: Dict[str, float] = {}
        os.makedirs(RAW_DIR, exist_ok=True)

    def close(self):
        self.client.close()

    def _throttle(self, host: str):
        wait = MIN_INTERVAL_S - (time.time() - self._last_hit.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        self._last_hit[host] = time.time()

    def robots_allows(self, url: str) -> Tuple[bool, str]:
        p = urllib.parse.urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self._robots:
            self._throttle(p.netloc)
            try:
                r = self.client.get(base + "/robots.txt")
                if r.status_code in (401, 403):
                    self._robots[base], self._robots_status[base] = None, f"robots.txt {r.status_code}: disallow"
                elif 400 <= r.status_code < 500:
                    rp = urllib.robotparser.RobotFileParser()
                    rp.parse([])
                    self._robots[base], self._robots_status[base] = rp, f"robots.txt {r.status_code}: no rules"
                elif r.status_code >= 500:
                    self._robots[base], self._robots_status[base] = None, f"robots.txt {r.status_code}: disallow"
                else:
                    rp = urllib.robotparser.RobotFileParser()
                    rp.parse(r.text.splitlines())
                    self._robots[base], self._robots_status[base] = rp, "robots.txt ok"
            except Exception as e:
                self._robots[base], self._robots_status[base] = None, f"robots.txt unreachable ({type(e).__name__})"
        rp = self._robots[base]
        if rp is None:
            return False, self._robots_status[base]
        return rp.can_fetch(USER_AGENT, url), self._robots_status[base]

    def fetch(self, url: str) -> FetchResult:
        bin_path, meta_path = _cache_paths(url)
        if self.use_cache and os.path.exists(bin_path) and os.path.exists(meta_path):
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
            with open(bin_path, "rb") as f:
                body = f.read()
            if is_bot_challenge(body):  # stale cache entry from an older run
                os.remove(bin_path)
                os.remove(meta_path)
                return self.fetch(url)
            return FetchResult(url=url, ok=True, status=meta.get("status"), content_type=meta.get("content_type", ""),
                               body=body, from_cache=True, final_url=meta.get("final_url", url))

        allowed, why = self.robots_allows(url)
        if not allowed:
            return FetchResult(url=url, ok=False, error=f"blocked by robots policy ({why})")

        host = urllib.parse.urlparse(url).netloc
        self._throttle(host)
        try:
            r = self.client.get(url)
        except Exception as e:
            return FetchResult(url=url, ok=False, error=f"{type(e).__name__}: {e}"[:200])
        if r.status_code != 200 or not r.content:
            return FetchResult(url=url, ok=False, status=r.status_code, error=f"HTTP {r.status_code}")
        ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
        if is_bot_challenge(r.content):
            return FetchResult(url=url, ok=False, status=r.status_code,
                               error="site served a bot-protection challenge (not bypassed)")
        with open(bin_path, "wb") as f:
            f.write(r.content)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({"url": url, "final_url": str(r.url), "status": r.status_code, "content_type": ctype,
                       "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, f)
        return FetchResult(url=url, ok=True, status=r.status_code, content_type=ctype, body=r.content,
                           final_url=str(r.url))


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

_DATE_PATTERNS = [
    re.compile(r"\b((?:January|February|March|April|May|June|July|August|September|October|November|December)"
               r"\s+\d{1,2},\s+(?:19|20)\d{2})\b"),
    re.compile(r"\b(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*,?\s+(?:19|20)\d{2})\b"),
    re.compile(r"\b(\d{1,2}[./-]\d{1,2}[./-](?:19|20)\d{2})\b"),
]


def detect_language(text: str) -> str:
    sample = text[:4000]
    deva = sum(1 for ch in sample if "ऀ" <= ch <= "ॿ")
    tamil = sum(1 for ch in sample if "஀" <= ch <= "௿")
    latin = sum(1 for ch in sample if ch.isascii() and ch.isalpha())
    counts = {"hi": deva, "ta": tamil, "en": latin}
    return max(counts, key=counts.get) if any(counts.values()) else "en"


def find_date(text: str) -> Optional[str]:
    head = text[:3000]
    for pat in _DATE_PATTERNS:
        m = pat.search(head)
        if m:
            return m.group(1)
    return None


_BOILERPLATE = re.compile(
    r"^(skip to main content|screen reader access|home|login|sitemap|contact us|feedback|"
    r"a\+|a-|a|text size|print|share|back|top|close|menu|search|español|हिन्दी|हिंदी|english|not pressed|"
    r"change language( हिंदी)?|search the website|\(\s*\d+\s*kb\s*\))$", re.I)


_MONTH_LIST = re.compile(r"(all months\s+)?january\s+february\s+march", re.I)


def _clean_lines(lines: List[str]) -> List[str]:
    out, prev = [], None
    for ln in lines:
        ln = re.sub(r"\s+", " ", ln).strip()
        if not ln or len(ln) < 3 or _BOILERPLATE.match(ln) or ln == prev or _MONTH_LIST.search(ln):
            continue
        out.append(ln)
        prev = ln
    return out


_TITLE_GENERIC = re.compile(
    r"official website|press release page|press information bureau|^reserve bank of india$|^notifications?$|"
    r"^press releases?\s*$|^untitled|^advisories$|^master directions?( - reserve bank of india)?$|^publications$|"
    r"^pr no\.?\s*\d+/\d+$|^government of india$|^ministry of|^dbod$|^banker to government|^cert-in advisory ciad|"
    r"^page \d+ of \d+$|^date\s*:|^for digital nagriks|^financial inclusion and development|^\(?\s*\d+\s*kb|"
    r"^original issue date|^severity rating|^rbi/\d{4}|^[\W\d]+$", re.I)


def _better_title(title: str, text: str, generic_re=None) -> str:
    """If the page title is a generic site label, use the first meaningful line of the document."""
    title = (title or "").strip()
    if title and not _TITLE_GENERIC.search(title) and not (generic_re and generic_re.search(title)):
        return title
    for ln in text.splitlines()[:60]:
        t = ln.lstrip("# ").strip()
        if 15 <= len(t) <= 200 and not _TITLE_GENERIC.search(t) and not (generic_re and generic_re.search(t)):
            return t
    return title


def extract_html(body: bytes, url: str) -> ExtractedDoc:
    from bs4 import BeautifulSoup
    try:
        soup = BeautifulSoup(body.decode("utf-8"), "html.parser")
    except UnicodeDecodeError:
        soup = BeautifulSoup(body, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "iframe", "svg", "button"]):
        tag.decompose()
    junk = re.compile(r"(^|[-_ ])(menu|submenu\d*|centermenu|navbar|nav|footer|header|breadcrumb|sidebar|archive\w*|"
                      r"divarchivemain|social|share|skip)([-_ ]|$)", re.I)
    for t in soup.find_all(True):
        if t.attrs is None or t.name in ("html", "body"):
            continue
        ident = " ".join([t.get("id") or ""] + list(t.get("class") or [])).strip()
        if ident and junk.search(ident):
            t.decompose()

    title = ""
    h1 = soup.find(["h1", "h2"])
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    generic_re = re.compile(r"official website|press release page|press information bureau|^reserve bank of india$|"
                            r"^notifications?$|^press releases?\s*$|^untitled|^advisories$|^master directions?$|"
                            r"^frequently asked questions$|^faqs?$|change language|search the website|not pressed|"
                            r"^master directions? - reserve bank|^publications$|^press release|^pr no\.?|"
                            r"^government of india$|^ministry of|^dbod$|^banker to government|^cert-in advisory ciad|"
                            r"^page \d+ of \d+$|^date\s*:", re.I)
    generic = (not title) or bool(generic_re.search(title.strip()))
    # Prefer the document's own heading over a generic site <title>
    # Known content containers on official sites, tried before the generic heuristic.
    for sel in ("#lblData", "span[id$=lblData]", "td.textDetails", "#ContentPlaceHolder1_divContent",
                "div.innner-page-main-about-us-content-right-part", "div.content-area", "#content"):
        hit = soup.select_one(sel)
        if hit is not None and len(hit.get_text(" ", strip=True)) > 200:
            preferred = hit
            break
    else:
        preferred = None
    candidates = [preferred] if preferred is not None else [soup.find("main"), soup.find("article")]
    if preferred is None:
        candidates += soup.find_all(["div", "td", "section", "table"], id=re.compile("content|main", re.I))
        candidates += soup.find_all(["div", "td", "section", "table"], class_=re.compile("content|main", re.I))
    candidates = [c for c in candidates if c is not None and len(c.get_text(" ", strip=True)) > 200]
    main = max(candidates, key=lambda c: len(c.get_text(" ", strip=True))) if candidates else (soup.body or soup)
    for cand in main.find_all(["h1", "h2", "h3", "b", "strong", "p", "td"], limit=40) if generic else []:
        t = re.sub(r"\s+", " ", cand.get_text(" ", strip=True))
        if 12 <= len(t) <= 200 and not generic_re.search(t) and not re.search(
                r"skip|screen reader|menu|login|date\s*:|^\(?\s*\d+\s*kb\s*\)?$|^home\s*>>", t, re.I):
            title = t
            break
    if not title and h1:
        title = h1.get_text(" ", strip=True)

    lines, sections = [], []
    for el in main.find_all(["h1", "h2", "h3", "h4", "p", "li", "td", "div"], recursive=True):
        if el.name == "div" and el.find(["p", "li", "td", "div", "h1", "h2", "h3", "h4"]):
            continue  # only leaf-ish divs, to avoid duplicating nested text
        txt = el.get_text(" ", strip=True)
        if not txt:
            continue
        if el.name in ("h1", "h2", "h3", "h4") and len(txt) < 200:
            lines.append(f"# {txt}")
            sections.append(txt)
        else:
            lines.append(txt)
    text = "\n".join(_clean_lines(lines))
    title = _better_title(title, text, generic_re)
    return ExtractedDoc(title=title[:300], text=text, language=detect_language(text),
                        published_date=find_date(text), sections=sections)


def extract_pdf(body: bytes, url: str) -> ExtractedDoc:
    import io
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(body))
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")
    raw_lines = "\n".join(pages).splitlines()
    lines = []
    for ln in _clean_lines(raw_lines):
        # Short title-case / upper-case lines without terminal punctuation are probably headings.
        if 4 <= len(ln) <= 90 and not ln.endswith((".", ",", ";", ":")) and (ln.isupper() or ln.istitle()):
            lines.append(f"# {ln}")
        else:
            lines.append(ln)
    text = "\n".join(lines)
    meta_title = ""
    try:
        meta_title = (reader.metadata.title or "").strip() if reader.metadata else ""
    except Exception:
        pass
    if not meta_title or re.search(r"untitled|microsoft word|\.pdf$|^\w+\d+|handbook_|_final|bleed", meta_title, re.I):
        meta_title = ""
    meta_title = _better_title(meta_title, text)
    return ExtractedDoc(title=meta_title[:300], text=text, language=detect_language(text),
                        published_date=find_date(text))


def extract(result: FetchResult) -> ExtractedDoc:
    is_pdf = "pdf" in result.content_type or result.body[:5] == b"%PDF-" or result.url.lower().endswith(".pdf")
    return extract_pdf(result.body, result.url) if is_pdf else extract_html(result.body, result.url)
