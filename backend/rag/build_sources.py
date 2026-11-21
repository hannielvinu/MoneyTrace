"""
Turn discovered candidates into the reviewed source list `rag/sources.yaml`.

Steps (all logged in rag/build_sources_report.json):
1. Drop URLs that are clearly not victim-facing advisories (annual reports, tenders,
   index/listing pages, login pages, duplicates in other UI languages, ...).
2. Canonicalise and de-duplicate (same PRID / Id on www. and m. hosts, etc.).
3. Fetch each remaining URL politely (robots.txt respected, cached in rag/raw/).
4. Keep documents whose extracted text is long enough and is actually about
   fraud response (keyword relevance score), then write sources.yaml.

Documents that could not be fetched from *this* machine are still written to
sources.yaml with `status: unfetched` so `make ingest` on another machine
(e.g. a laptop that the site does not block) can try them again.

    python -m rag.build_sources
"""

import json
import os
import re
import sys
import urllib.parse
from collections import OrderedDict
from typing import Dict, List, Optional

import yaml

from rag.fetch import PoliteFetcher, extract

HERE = os.path.dirname(__file__)

ISSUERS = OrderedDict([
    ("sachet.rbi.org.in", "RBI (Sachet)"), ("rbi.org.in", "Reserve Bank of India"),
    ("upihelp.npci.org.in", "NPCI"), ("npci.org.in", "NPCI"),
    ("cybercrime.gov.in", "National Cyber Crime Reporting Portal (MHA)"),
    ("i4c.mha.gov.in", "I4C, Ministry of Home Affairs"), ("mha.gov.in", "Ministry of Home Affairs"),
    ("pib.gov.in", "Press Information Bureau, Government of India"),
    ("cert-in.org.in", "CERT-In"), ("csk.gov.in", "CERT-In (Cyber Swachhta Kendra)"),
    ("sancharsaathi.gov.in", "Department of Telecommunications (Sanchar Saathi)"),
    ("dot.gov.in", "Department of Telecommunications"),
    ("sebi.gov.in", "SEBI"), ("incometax.gov.in", "Income Tax Department"),
    ("uidai.gov.in", "UIDAI"), ("meity.gov.in", "MeitY"),
])

EXCLUDE = [
    r"screenreader", r"annualreport", r"annual[_ %-]?report", r"tender", r"bs_viewbulletin", r"speeches",
    r"indiancurrency", r"circularindexdisplay", r"product-statistics", r"brand_guidelines", r"/order_",
    r"master%20circular%20for%20portfolio", r"1752664428748", r"privacy-policy", r"/login", r"complaint-status",
    r"track-complaint", r"owasp-csrftoken", r"from=appagg", r"meity\.gov\.in/static/uploads/2024/02/",
    r"meity\.gov\.in/static/uploads/2026/04", r"uidai\.gov\.in/images/", r"cyber_digest", r"content%20creation",
    r"samvaad", r"whtpview", r"pubadvlist", r"pubwel03", r"cyber-awareness-videos", r"inv_aware_edu_videos",
    r"recent-updates", r"/helpdesk\.aspx", r"communicationpolicy", r"aboutusdisplay", r"bs_viewmasdirections\.aspx$",
    r"bs_viewmasterdirections\.aspx$", r"/punjabi/", r"/oriya/", r"/marathi/", r"/urdu/", r"cashless-payments-made-easy",
    r"upi-one-world", r"/purpose-value", r"credit-card-on-upi", r"upi-lite", r"reserve_pay", r"upi_circle",
    r"ru_pay_consolidated", r"financialmarketswatch", r"bs_viewcontent\.aspx\?id=4235", r"fs_pressrelease\.aspx\?fn=",
    r"publicationreportdetails", r"bol\.pdf", r"settinglimits_video", r"flcs_cfls_details", r"nbfcfaqs",
    r"cdn\.cseindia", r"freeair", r"wtm/kv", r"asmita_patel", r"feb-2021/1612940539512", r"chapter%2008",
    r"policy%20related", r"/static/uploads/2026/10/", r"investor\.sebi\.gov\.in/?$", r"npci\.org\.in/?$",
    r"sancharsaathi\.gov\.in/?$", r"csk\.gov\.in/?$", r"index-hi\.html", r"/e-filing%20account", r"refund status",
    r"income-tax-form-upload", r"e-filing-services/login", r"dpssti6b55", r"/what-we-do/upi/product-overview",
    r"/product/upi/?$", r"/product/upi/about-upi", r"exchange-banknote", r"/sachet/?$", r"aadhaar-online-services",
    r"/en/authentication$", r"/webform/accept\.aspx", r"commonman/english/scripts/pressreleases\.aspx$",
    r"scripts/faqs\.aspx$", r"/publicationsview\.aspx\?id=23813",
]

# Extra language variants of one RBI awareness page (verified by fetching; dropped if they 404).
EXTRA_URLS = [
    "https://www.rbi.org.in/commonman/English/Scripts/FLW24_DigitalCyberHygiene.aspx",
    "https://www.rbi.org.in/commonman/Hindi/Scripts/FLW24_DigitalCyberHygiene.aspx",
    "https://www.rbi.org.in/commonman/Tamil/Scripts/FLW24_DigitalCyberHygiene.aspx",
]

KEYWORDS = [
    "fraud", "scam", "cyber", "upi", "otp", "phishing", "kyc", "1930", "complaint", "unauthori", "liability",
    "caution", "beware", "fake", "mule", "ombudsman", "dispute", "refund", "impersonat", "vishing", "smishing",
    "digital arrest", "loan app", "investment", "pin", "remote access", "screen shar", "helpline", "report",
    "धोखाधड़ी", "साइबर", "மோசடி", "சைபர்",
]
CORE = ["fraud", "scam", "upi", "otp", "phishing", "kyc", "1930", "unauthori", "mule", "impersonat", "vishing",
        "smishing", "digital arrest", "loan app", "धोखाधड़ी", "மோசடி", "fake"]


def issuer_for(url: str) -> str:
    host = urllib.parse.urlparse(url).netloc.lower()
    for dom, name in ISSUERS.items():
        if host == dom or host.endswith("." + dom):
            return name
    return host


def canonical(url: str) -> str:
    p = urllib.parse.urlparse(url.strip())
    host = p.netloc.lower()
    if host in ("m.rbi.org.in", "rbi.org.in"):
        host = "www.rbi.org.in"
    if host in ("pib.gov.in",):
        host = "www.pib.gov.in"
    if host in ("cert-in.org.in",):
        host = "www.cert-in.org.in"
    if host in ("cybercrime.gov.in",):
        host = "www.cybercrime.gov.in"
    if host in ("sancharsaathi.gov.in",):
        host = "www.sancharsaathi.gov.in"
    q = urllib.parse.parse_qs(p.query, keep_blank_values=True)
    keep = {}
    for k, v in q.items():
        if k.lower() in ("id", "prid", "vlcode", "pageid", "sid", "noteid", "moduleid", "urlpage", "search"):
            keep[k.lower()] = v[0]
    query = urllib.parse.urlencode(sorted(keep.items()))
    path = p.path
    if "rbi.org.in" in host or "pib.gov.in" in host:
        path = path.lower()
    return urllib.parse.urlunparse(("https", host, path, "", query, ""))


def dedupe_key(url: str) -> str:
    c = canonical(url)
    # PIB press releases appear under several page names; the PRID identifies them.
    m = re.search(r"pib\.gov\.in/.*[?&]prid=(\d+)", c)
    if m:
        return f"pib:{m.group(1)}"
    return c.lower()


def relevance(text: str) -> int:
    """Keyword score; 0 unless at least two core fraud-response terms appear."""
    low = text.lower()
    if sum(1 for k in CORE if k in low) < 2:
        return 0
    return sum(min(low.count(k), 5) for k in KEYWORDS)


def make_doc_id(url: str, issuer: str) -> str:
    short = {"Reserve Bank of India": "rbi", "NPCI": "npci", "SEBI": "sebi", "CERT-In": "certin", "UIDAI": "uidai",
             "Income Tax Department": "itd"}.get(issuer, re.sub(r"[^a-z]+", "", issuer.lower())[:8] or "doc")
    import hashlib
    return f"{short}-{hashlib.sha1(canonical(url).encode()).hexdigest()[:8]}"


def _parse_date(d: Optional[str]):
    from datetime import datetime
    if not d:
        return None
    for fmt in ("%B %d, %Y", "%d %B %Y", "%d %b %Y", "%d %b, %Y", "%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(d.replace(",", ", ").replace("  ", " ").strip(), fmt)
        except ValueError:
            continue
    return None


def apply_curation(sources: List[Dict]):
    """Rule-based + manual (rag/source_overrides.yaml) curation. Every exclusion records a reason."""
    path = os.path.join(HERE, "source_overrides.yaml")
    overrides = yaml.safe_load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    excl = overrides.get("exclude") or {}
    fixes = overrides.get("fix") or {}
    for s in sources:
        s["include"] = True
        title = (s.get("title") or "")
        if s["url"] in excl:
            s["include"], s["exclude_reason"] = False, excl[s["url"]]
        elif re.search(r"^draft|draft circular|draft amendment|seeks comments", title, re.I):
            s["include"], s["exclude_reason"] = False, "draft for public comment, not in force"
        elif re.search(r"\bwithdrawn\b", title, re.I):
            s["include"], s["exclude_reason"] = False, "withdrawn"
        for k, v in (fixes.get(s["url"]) or {}).items():
            s[k] = v
    # Superseded editions: same title, keep the newest dated one.
    groups: Dict[str, List[Dict]] = {}
    for s in sources:
        if s["include"] and s.get("title"):
            groups.setdefault(re.sub(r"\W+", " ", s["title"].lower()).strip(), []).append(s)
    for g in groups.values():
        if len(g) < 2:
            continue
        g.sort(key=lambda x: _parse_date(x.get("published_date")) or _parse_date("01/01/1900"), reverse=True)
        for old in g[1:]:
            old["include"], old["exclude_reason"] = False, f"superseded by newer edition {g[0]['doc_id']}"


def main(min_chars: int = 400, min_relevance: int = 6):
    cands = json.load(open(os.path.join(HERE, "sources_candidates.json"), encoding="utf-8"))
    urls = [c["url"] for c in cands] + EXTRA_URLS
    report = {"candidates": len(urls), "excluded": [], "duplicates": [], "fetch_failed": [], "irrelevant": [], "kept": []}

    unique: "OrderedDict[str, str]" = OrderedDict()
    for u in urls:
        low = u.lower()
        if any(re.search(p, low) for p in EXCLUDE):
            report["excluded"].append(u)
            continue
        k = dedupe_key(u)
        if k in unique:
            report["duplicates"].append(u)
            continue
        # PIB: prefer the plain PressReleasePage (English) form
        m = re.search(r"prid=(\d+)", low)
        unique[k] = f"https://www.pib.gov.in/PressReleasePage.aspx?PRID={m.group(1)}" if k.startswith("pib:") and m else u

    fetcher = PoliteFetcher()
    sources, seen_text = [], {}
    try:
        for i, url in enumerate(unique.values(), 1):
            res = fetcher.fetch(url)
            issuer = issuer_for(url)
            entry = {"doc_id": make_doc_id(url, issuer), "url": url, "issuer": issuer}
            if not res.ok:
                report["fetch_failed"].append({"url": url, "error": res.error})
                sources.append({**entry, "title": None, "published_date": None, "language": None,
                                "status": "unfetched", "note": res.error})
                print(f"[{i}/{len(unique)}] FAIL {res.error[:60]} {url}")
                continue
            try:
                doc = extract(res)
            except Exception as e:
                report["fetch_failed"].append({"url": url, "error": f"extract failed: {type(e).__name__}"})
                print(f"[{i}/{len(unique)}] EXTRACT-FAIL {type(e).__name__} {url}")
                continue
            score = relevance(doc.text)
            fingerprint = re.sub(r"\W+", "", doc.text[:1500].lower())
            if fingerprint in seen_text:
                report["duplicates"].append(url)
                continue
            if len(doc.text) < min_chars or score < min_relevance:
                report["irrelevant"].append({"url": url, "chars": len(doc.text), "relevance": score, "title": doc.title})
                print(f"[{i}/{len(unique)}] skip chars={len(doc.text)} rel={score} {url}")
                continue
            seen_text[fingerprint] = url
            sources.append({**entry, "title": doc.title or url, "published_date": doc.published_date,
                            "language": doc.language, "status": "fetched", "chars": len(doc.text), "relevance": score})
            report["kept"].append(url)
            print(f"[{i}/{len(unique)}] keep rel={score} chars={len(doc.text)} {doc.title[:60]!r}")
    finally:
        fetcher.close()

    header = (
        "# Official fraud-response sources for the MoneyTrace RAG corpus.\n"
        "# Generated by `python -m rag.build_sources` from rag/sources_candidates.json, then reviewed by a human.\n"
        "# REVIEW: set `include: false` on anything that should not be used for victim guidance.\n"
        "# status: fetched   -> downloaded from this machine and passed the relevance screen\n"
        "#         unfetched -> the site refused this machine (robots/403/timeout); `make ingest` retries it\n"
    )
    apply_curation(sources)
    with open(os.path.join(HERE, "sources.yaml"), "w", encoding="utf-8") as f:
        f.write(header)
        yaml.safe_dump({"sources": sources}, f, allow_unicode=True, sort_keys=False, width=140)
    report["summary"] = {k: len(v) for k, v in report.items() if isinstance(v, list)}
    with open(os.path.join(HERE, "build_sources_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(json.dumps(report["summary"]))
    fetched = sum(1 for s in sources if s["status"] == "fetched")
    print(f"sources.yaml: {len(sources)} entries ({fetched} fetched, {len(sources) - fetched} unfetched)")


if __name__ == "__main__":
    main()
