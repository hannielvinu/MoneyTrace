"""
Discover candidate advisory documents on official Indian government / regulator sites.

This script only *proposes* sources: it runs web searches restricted to official
domains and writes `rag/sources_candidates.json`. A human (Hanniel) reviews the
list, and `rag/build_sources.py` turns accepted candidates into `rag/sources.yaml`.

Search backend: Tavily (TAVILY_API_KEY, or a proxy that injects it).

    python -m rag.discover_sources
"""

import json
import os
import sys
import time
from typing import Dict, List

import httpx

OFFICIAL_DOMAINS = [
    "rbi.org.in", "npci.org.in", "cybercrime.gov.in", "cert-in.org.in", "i4c.mha.gov.in",
    "mha.gov.in", "pib.gov.in", "sachet.rbi.org.in", "sancharsaathi.gov.in", "dot.gov.in",
    "meity.gov.in", "sebi.gov.in", "consumerhelpline.gov.in", "incometax.gov.in",
    "uidai.gov.in", "csk.gov.in", "cdn.cseindia.org",
]

QUERIES: List[Dict] = [
    # RBI regulation and customer liability
    {"q": "RBI customer protection limiting liability of customers unauthorised electronic banking transactions circular", "d": ["rbi.org.in"]},
    {"q": "RBI master direction fraud risk management commercial banks 2024", "d": ["rbi.org.in"]},
    {"q": "RBI master direction digital payment security controls", "d": ["rbi.org.in"]},
    {"q": "RBI harmonisation of turn around time customer compensation failed transactions authorised payment systems", "d": ["rbi.org.in"]},
    {"q": "RBI integrated ombudsman scheme how to file complaint", "d": ["rbi.org.in"]},
    {"q": "RBI complaint management system cms.rbi.org.in lodge complaint", "d": ["rbi.org.in"]},
    {"q": "RBI framework for authentication of digital payment transactions", "d": ["rbi.org.in"]},
    {"q": "RBI press release caution against fraudulent emails calls SMS in the name of RBI", "d": ["rbi.org.in"]},
    {"q": "RBI cautions public against fake KYC updation frauds", "d": ["rbi.org.in"]},
    {"q": "RBI cautions against unauthorised forex trading platforms alert list", "d": ["rbi.org.in"]},
    {"q": "RBI cautions public against digital loan apps unauthorised lending", "d": ["rbi.org.in"]},
    {"q": "RBI cautions public deepfake videos governor investment schemes", "d": ["rbi.org.in"]},
    {"q": "RBI BE(A)WARE booklet modus operandi of financial frauds", "d": ["rbi.org.in"]},
    {"q": "RBI Kehta Hai financial frauds awareness", "d": ["rbi.org.in"]},
    {"q": "RBI FAQ customer liability unauthorised electronic transactions", "d": ["rbi.org.in"]},
    {"q": "RBI FAQ unified payments interface UPI customers", "d": ["rbi.org.in"]},
    {"q": "RBI FAQs on fraud prevention safe digital banking", "d": ["rbi.org.in"]},
    {"q": "RBI MuleHunter AI mule accounts", "d": ["rbi.org.in"]},
    {"q": "RBI SIM swap fraud OTP sharing precaution", "d": ["rbi.org.in"]},
    {"q": "RBI financial literacy week cyber hygiene", "d": ["rbi.org.in"]},
    {"q": "RBI reporting of frauds by customers bank timeline zero liability three days", "d": ["rbi.org.in"]},
    {"q": "RBI dial 1930 cyber fraud reporting press release", "d": ["rbi.org.in"]},
    {"q": "RBI digital arrest scam caution public", "d": ["rbi.org.in"]},
    {"q": "Sachet RBI report unauthorised deposit schemes", "d": ["sachet.rbi.org.in", "rbi.org.in"]},
    # NPCI
    {"q": "NPCI UPI safety tips do's and don'ts", "d": ["npci.org.in"]},
    {"q": "NPCI UPI dispute redressal mechanism raise complaint", "d": ["npci.org.in"]},
    {"q": "NPCI UPI collect request fraud never enter PIN to receive money", "d": ["npci.org.in"]},
    {"q": "NPCI safe digital payments awareness campaign fraud", "d": ["npci.org.in"]},
    {"q": "NPCI circular UPI fraud risk management", "d": ["npci.org.in"]},
    # Cybercrime portal, I4C, MHA, PIB
    {"q": "National Cyber Crime Reporting Portal report financial fraud 1930 helpline", "d": ["cybercrime.gov.in", "i4c.mha.gov.in", "mha.gov.in"]},
    {"q": "Citizen Financial Cyber Fraud Reporting and Management System 1930", "d": ["pib.gov.in", "mha.gov.in", "i4c.mha.gov.in"]},
    {"q": "I4C advisory digital arrest scam citizens", "d": ["pib.gov.in", "i4c.mha.gov.in", "mha.gov.in"]},
    {"q": "PIB cyber fraud awareness UPI fraud steps taken government", "d": ["pib.gov.in"]},
    {"q": "PIB investment task based scam advisory part time job fraud", "d": ["pib.gov.in"]},
    {"q": "PIB fake customer care number fraud advisory", "d": ["pib.gov.in"]},
    {"q": "PIB screen sharing app remote access fraud advisory", "d": ["pib.gov.in"]},
    {"q": "PIB mule accounts suspect registry I4C", "d": ["pib.gov.in"]},
    {"q": "PIB sextortion and loan app harassment cyber crime advisory", "d": ["pib.gov.in"]},
    {"q": "PIB Sanchar Saathi Chakshu report suspected fraud communication", "d": ["pib.gov.in", "sancharsaathi.gov.in", "dot.gov.in"]},
    {"q": "Sanchar Saathi Chakshu report fraud call SMS WhatsApp", "d": ["sancharsaathi.gov.in", "dot.gov.in"]},
    # CERT-In / MeitY
    {"q": "CERT-In advisory online financial fraud safety", "d": ["cert-in.org.in", "csk.gov.in"]},
    {"q": "CERT-In advisory phishing smishing UPI", "d": ["cert-in.org.in", "csk.gov.in"]},
    {"q": "Cyber Swachhta Kendra security tips online banking", "d": ["csk.gov.in"]},
    {"q": "MeitY cyber security awareness online fraud", "d": ["meity.gov.in"]},
    # Other regulators touching common scams
    {"q": "SEBI caution investors fraudulent trading WhatsApp Telegram groups", "d": ["sebi.gov.in"]},
    {"q": "SEBI investor alert fake trading apps impersonation", "d": ["sebi.gov.in"]},
    {"q": "Income tax department caution fake refund SMS phishing", "d": ["incometax.gov.in", "pib.gov.in"]},
    {"q": "UIDAI aadhaar enabled payment system fraud lock biometrics", "d": ["uidai.gov.in", "pib.gov.in"]},
]


def tavily_search(client: httpx.Client, query: str, domains: List[str], max_results: int = 8) -> List[Dict]:
    key = os.environ.get("TAVILY_API_KEY", "proxy-injected")
    r = client.post("https://api.tavily.com/search", json={
        "query": query, "max_results": max_results, "include_domains": domains, "search_depth": "advanced",
    }, headers={"Authorization": f"Bearer {key}"})
    r.raise_for_status()
    return r.json().get("results", [])


def main(out_path: str = None):
    out_path = out_path or os.path.join(os.path.dirname(__file__), "sources_candidates.json")
    seen: Dict[str, Dict] = {}
    with httpx.Client(timeout=60) as client:
        for i, item in enumerate(QUERIES, 1):
            try:
                results = tavily_search(client, item["q"], item["d"])
            except Exception as e:
                print(f"[{i}/{len(QUERIES)}] search failed: {e}", file=sys.stderr)
                continue
            for r in results:
                url = r["url"].split("#")[0]
                if not any(d in url for d in OFFICIAL_DOMAINS):
                    continue
                seen.setdefault(url, {"url": url, "title": r.get("title", "").strip(),
                                      "snippet": (r.get("content") or "")[:300], "queries": []})
                seen[url]["queries"].append(item["q"])
            print(f"[{i}/{len(QUERIES)}] {len(results)} results, {len(seen)} unique so far")
            time.sleep(0.5)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(sorted(seen.values(), key=lambda x: x["url"]), f, indent=2, ensure_ascii=False)
    print(f"wrote {len(seen)} candidates to {out_path}")


if __name__ == "__main__":
    main()
