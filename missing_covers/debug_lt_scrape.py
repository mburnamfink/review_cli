#!/usr/bin/env python3
"""Try scraping LibraryThing cover via BeautifulSoup."""

import sys
import httpx
from bs4 import BeautifulSoup

ISBN = sys.argv[1] if len(sys.argv) > 1 else "9780451042507"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

url = f"https://www.librarything.com/isbn/{ISBN}"
print(f"Fetching: {url}\n")

with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=15) as client:
    r = client.get(url)

print(f"Status: {r.status_code}")
print(f"Content-Type: {r.headers.get('content-type')}")
print(f"Final URL: {r.url}")
print(f"Size: {len(r.text)} chars\n")

if r.status_code != 200:
    print("Response body (first 1000 chars):")
    print(r.text[:1000])
    sys.exit(1)

soup = BeautifulSoup(r.text, "html.parser")

# Look for cover images
print("=== Images with 'cover' in src or class ===")
for img in soup.find_all("img"):
    src = img.get("src", "")
    cls = " ".join(img.get("class", []))
    alt = img.get("alt", "")
    if any(k in src.lower() for k in ("cover", "thingcover", "work")) or "cover" in cls.lower():
        print(f"  src={src!r}  class={cls!r}  alt={alt!r}")

# Look for og:image meta tag
print("\n=== OG / meta image tags ===")
for tag in soup.find_all("meta"):
    name = tag.get("property", "") or tag.get("name", "")
    if "image" in name.lower():
        print(f"  {name} = {tag.get('content')}")

# Dump all img srcs for inspection
print("\n=== All img srcs ===")
for img in soup.find_all("img"):
    print(f"  {img.get('src')}")
