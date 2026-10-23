"""2. ANALYSIS (inputs) - what AI models can actually read about a restaurant.
Scrapes a site, parses JSON-LD schema, checks the signals that matter.
Respect rate limits: fetch once, cache the result, don't loop sites live in demo.
"""
import json, re, statistics, requests
from urllib.parse import urljoin
from bs4 import BeautifulSoup

DIETARY = ["vegan", "gluten-free", "gluten free", "vegetarian", "halal", "kosher", "keto"]
HEADERS = {"User-Agent": "PlateRank-Hackathon/1.0"}
PRICE = re.compile(r"\$\s?(\d{1,3}(?:\.\d{2})?)")

def _soup(url: str) -> BeautifulSoup:
    return BeautifulSoup(requests.get(url, timeout=10, headers=HEADERS).text, "html.parser")

def menu_prices(url: str, anchor_item: str | None = None) -> dict:
    """Best-effort price read for the AREA BENCHMARK: fetch the site once, follow
    its 'menu' link if any, collect $ prices from the HTML text. PDF/image/JS
    menus can't be read - then found=False and the owner types the prices in.
    The result is a suggestion the owner checks, never used silently."""
    try:
        soup, page = _soup(url), url
        link = next((a.get("href") for a in soup.find_all("a", href=True)
                     if "menu" in (a.get("href", "") + a.get_text(" ")).lower()), None)
        if link and link.lower().endswith(".pdf"):
            return {"url": urljoin(url, link), "found": False, "note": "menu is a PDF - type the prices in"}
        if link:
            page = urljoin(url, link)
            soup = _soup(page)
    except Exception as e:
        return {"url": url, "found": False, "note": f"couldn't fetch the site ({type(e).__name__})"}
    text = soup.get_text(" ", strip=True)
    prices = [float(p) for p in PRICE.findall(text) if 2 <= float(p) <= 300]
    anchor = None
    if anchor_item:
        m = re.search(re.escape(anchor_item) + r"[^$]{0,60}\$\s?(\d{1,3}(?:\.\d{2})?)", text, re.I)
        anchor = float(m.group(1)) if m else None
    if not prices:
        return {"url": page, "found": False, "note": "no $ prices in the page text (menu may be an image or app)"}
    return {"url": page, "found": True, "n_prices": len(prices), "median_price": statistics.median(prices),
            "anchor_price": anchor,
            "note": f"median of {len(prices)} prices found on the menu page - check it before using it"}

def _menu_page(soup: BeautifulSoup, base: str) -> str | None:
    """First on-site link that looks like the menu (and isn't a PDF itself)."""
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "menu" in (href + " " + a.get_text(" ")).lower() and not href.lower().endswith(".pdf") \
                and not href.startswith(("#", "mailto:", "tel:")):
            return urljoin(base, href)
    return None

def audit_website(url: str) -> dict:
    """What AI models can actually read about a restaurant: schema, menu format,
    FAQ, dietary tags, amount of text. Follows the site's own 'Menu' link once,
    so a menu that only exists as PDFs on a sub-page is caught too."""
    try:
        html = requests.get(url, timeout=10, headers=HEADERS).text
    except Exception as e:
        return {"url": url, "error": str(e)}
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True).lower()
    schema_types, has_menu_schema, has_faq_schema = [], False, False
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "{}")
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            t = item.get("@type", "") if isinstance(item, dict) else ""
            schema_types.append(t)
            has_menu_schema |= t in ("Menu", "MenuItem")
            has_faq_schema |= t == "FAQPage"
    links = [urljoin(url, a.get("href", "")) for a in soup.find_all("a")]
    pdf_menus = [l for l in links if l.lower().endswith(".pdf") and "menu" in l.lower()]
    menu_url, menu_prices_in_text = _menu_page(soup, url), None
    if menu_url:
        try:
            msoup = _soup(menu_url)
            pdf_menus += [urljoin(menu_url, a["href"]) for a in msoup.find_all("a", href=True)
                          if a["href"].lower().endswith(".pdf")]
            menu_prices_in_text = len(PRICE.findall(msoup.get_text(" ", strip=True)))
        except Exception:
            pass
    pdf_menus = sorted(set(pdf_menus))
    return {
        "url": url,
        "schema_types": schema_types,
        "has_restaurant_schema": any(t in ("Restaurant", "FoodEstablishment") for t in schema_types),
        "has_menu_schema": has_menu_schema,
        "has_faq_schema": has_faq_schema,
        "menu_page": menu_url,
        "menu_pdfs": pdf_menus,
        "menu_prices_in_page_text": menu_prices_in_text,
        # PDF-only = PDFs exist and the menu page itself shows (almost) no prices as text
        "menu_is_pdf": bool(pdf_menus) and (menu_prices_in_text or 0) < 5,
        "has_faq_page": "faq" in text or any("faq" in l.lower() for l in links),
        "dietary_tags_found": [d for d in DIETARY if d in text],
        "word_count": len(text.split()),
    }

def diagnose(target_audit: dict, comp_audit: dict, comp_name: str) -> list[str]:
    """Evidence-based gaps: target vs ONE top competitor. This is your demo gold."""
    gaps = []
    if not target_audit.get("has_restaurant_schema"):
        gaps.append("Target site has no Restaurant schema (JSON-LD) - AI can't read its name, address, hours "
                    "and cuisine as structured facts" + (f"; {comp_name} has it." if comp_audit.get("has_restaurant_schema") else "."))
    if comp_audit.get("has_menu_schema") and not target_audit.get("has_menu_schema"):
        gaps.append(f"{comp_name} has Menu schema AI can parse directly; target has none.")
    if comp_audit.get("dietary_tags_found") and not target_audit.get("dietary_tags_found"):
        gaps.append(f"{comp_name} lists dietary tags {comp_audit['dietary_tags_found']}; target lists none, so it loses every dietary query.")
    if target_audit.get("menu_is_pdf"):
        n = len(target_audit.get("menu_pdfs") or [])
        gaps.append(f"Target menu exists only as {n} PDF file{'s' if n != 1 else ''} - AI models largely can't parse it"
                    + ("; competitor menu is readable text." if not comp_audit.get("menu_is_pdf") else "."))
    if comp_audit.get("has_faq_page") and not target_audit.get("has_faq_page"):
        gaps.append(f"{comp_name} has an FAQ page answering customer questions directly; target has none.")
    if (comp_audit.get("word_count") or 0) > 2 * (target_audit.get("word_count") or 1):
        gaps.append(f"{comp_name}'s site has ~{comp_audit['word_count']} words vs target's ~{target_audit.get('word_count')} - far more citable content.")
    return gaps or ["No structural gaps found in site audit - look at reviews / third-party mentions next."]

MENU_PROMPT = ("Read this restaurant menu. List every dish or drink that has a price. Reply with ONLY a JSON "
               "array of objects with keys: name, price (a number, no $), section (the menu heading it sits "
               "under, or empty string). Copy names and prices exactly as printed; skip items without a price; "
               "never guess a price.")

def _menu_items(parsed) -> list[dict]:
    items = []
    for it in parsed:
        try:
            items.append({"name": str(it["name"]).strip(), "price": float(it["price"]),
                          "section": str(it.get("section") or "").strip()})
        except (KeyError, TypeError, ValueError):
            continue
    return items

def read_menu_file(data: bytes, mime: str) -> list[dict]:
    """Read dishes + prices from a menu PHOTO, SCREENSHOT, PDF or page text.
    Claude when an Anthropic key exists (reads PDFs and images natively), else Gemini.
    Returns [{name, price, section}] for the owner to check and pick from - never saved
    without the owner choosing items."""
    from . import llm
    if llm.has_key():
        import base64
        if mime == "text/plain":
            block = {"type": "text", "text": "MENU TEXT:\n" + data.decode("utf-8", "ignore")[:60000]}
        elif mime == "application/pdf":
            block = {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                     "data": base64.b64encode(data).decode()}}
        else:
            block = {"type": "image", "source": {"type": "base64", "media_type": mime,
                                                  "data": base64.b64encode(data).decode()}}
        r = llm.claude_call([block, {"type": "text", "text": MENU_PROMPT}], max_tokens=16000, effort="low")
        return _menu_items(llm.json_from(r.text or "[]"))
    import os
    from google import genai
    from google.genai import types
    from .discovery import _gemini_busy_safe, _json_from
    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    resp, _ = _gemini_busy_safe(client, [types.Part.from_bytes(data=data, mime_type=mime), MENU_PROMPT])
    return _menu_items(_json_from(resp.text or "[]"))

def read_menu_from_link(url: str) -> tuple[list[dict], str]:
    """Menu link -> items. A PDF is downloaded; a web page's text is read. Returns (items, source)."""
    if url.lower().split("?")[0].endswith(".pdf"):
        return read_menu_file(fetch_pdf(url), "application/pdf"), url
    html = requests.get(url, timeout=15, headers=HEADERS).text
    text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
    return read_menu_file(text.encode("utf-8"), "text/plain"), url

def fetch_pdf(url: str) -> bytes:
    """Download one menu PDF (used when a site's menu is PDF-only)."""
    r = requests.get(url, timeout=20, headers=HEADERS)
    r.raise_for_status()
    return r.content
