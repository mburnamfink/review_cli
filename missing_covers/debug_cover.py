#!/usr/bin/env python3
"""Debug cover fetching for a single ISBN — shows what each source returns."""

import sys
import httpx
import xml.etree.ElementTree as ET

import tomllib
from pathlib import Path

ISBN = sys.argv[1] if len(sys.argv) > 1 else "9780451042507"

_config_path = Path.home() / ".review" / "config.toml"
if _config_path.exists():
    with open(_config_path, "rb") as _f:
        _config = tomllib.load(_f)
    LT_KEY = _config.get("librarything_api_key") or None
else:
    LT_KEY = None

if len(sys.argv) > 2:
    LT_KEY = sys.argv[2]

print(f"\nDebugging cover fetch for ISBN: {ISBN}\n{'='*50}")


# --- Open Library ---
print("\n[1] Open Library")
url = f"https://covers.openlibrary.org/b/isbn/{ISBN}-L.jpg"
print(f"    URL: {url}")
try:
    r = httpx.get(url, timeout=15, follow_redirects=True)
    print(f"    Status: {r.status_code}")
    print(f"    Content-Type: {r.headers.get('content-type')}")
    print(f"    Size: {len(r.content)} bytes")
    print(f"    Result: {'OK' if len(r.content) >= 2000 else 'PLACEHOLDER (too small)'}")
except Exception as e:
    print(f"    ERROR: {e}")


# --- Google Books ---
print("\n[2] Google Books")
gb_url = "https://www.googleapis.com/books/v1/volumes"
params = {"q": f"isbn:{ISBN}"}
print(f"    URL: {gb_url}?q=isbn:{ISBN}")
try:
    r = httpx.get(gb_url, params=params, timeout=10)
    print(f"    Status: {r.status_code}")
    data = r.json()
    items = data.get("items") or []
    print(f"    Items returned: {len(items)}")
    if items:
        links = items[0].get("volumeInfo", {}).get("imageLinks", {})
        print(f"    Image links: {links}")
        img_url = (
            links.get("extraLarge") or links.get("large") or links.get("medium")
            or links.get("small") or links.get("thumbnail")
        )
        if img_url:
            img_url = img_url.replace("http://", "https://").replace("&zoom=1", "&zoom=0")
            print(f"    Fetching: {img_url}")
            ir = httpx.get(img_url, timeout=15, follow_redirects=True)
            print(f"    Image status: {ir.status_code}")
            print(f"    Image size: {len(ir.content)} bytes")
            print(f"    Result: {'OK' if len(ir.content) >= 2000 else 'PLACEHOLDER (too small)'}")
        else:
            print("    Result: NO IMAGE LINKS")
    else:
        print("    Result: NO ITEMS")
except Exception as e:
    print(f"    ERROR: {e}")


# --- WorldCat ---
print("\n[3] WorldCat")
wc_url = f"https://covers.worldcat.org/isbn/{ISBN}-L.jpg"
print(f"    URL: {wc_url}")
try:
    r = httpx.get(wc_url, timeout=15, follow_redirects=True)
    print(f"    Status: {r.status_code}")
    print(f"    Content-Type: {r.headers.get('content-type')}")
    print(f"    Size: {len(r.content)} bytes")
    print(f"    Result: {'OK' if len(r.content) >= 2000 else 'PLACEHOLDER (too small)'}")
except Exception as e:
    print(f"    ERROR: {e}")


# --- LibraryThing ---
print("\n[4] LibraryThing")
if not LT_KEY:
    print("    SKIPPED (no API key — pass as second argument)")
else:
    lt_url = "https://www.librarything.com/services/rest/1.1/"
    params = {"method": "librarything.ck.getwork", "isbn": ISBN, "apikey": LT_KEY}
    print(f"    URL: {lt_url} method=librarything.ck.getwork isbn={ISBN}")
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Referer": "https://www.librarything.com/",
    }
    try:
        r = httpx.get(lt_url, params=params, timeout=10, headers=headers)
        print(f"    Status: {r.status_code}")
        print(f"    Raw response:\n{r.text[:800]}")
        root = ET.fromstring(r.text)
        stat = root.get("stat")
        print(f"    stat={stat}")
        src = root.findtext(".//covers/cover/src")
        print(f"    Cover src: {src}")
        if src:
            ir = httpx.get(src, timeout=15, follow_redirects=True)
            print(f"    Image status: {ir.status_code}")
            print(f"    Image size: {len(ir.content)} bytes")
            print(f"    Result: {'OK' if len(ir.content) >= 2000 else 'PLACEHOLDER (too small)'}")
        else:
            print("    Result: NO COVER SRC IN RESPONSE")
    except Exception as e:
        print(f"    ERROR: {e}")

print()
