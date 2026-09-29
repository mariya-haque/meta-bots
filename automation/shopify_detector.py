import httpx
import re
import json
from typing import Tuple, Dict, Any
from urllib.parse import urlparse

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Strictly block known large marketplaces and non-Shopify e-commerce sites to prevent false positives
MARKETPLACE_BLACKLIST = [
    "amazon.com", "amazon.co.uk", "amazon.in",
    "play.google.com", "itunes.apple.com", "apps.apple.com",
    "shein.com", "meesho.com", "meesho.onelink.me",
    "daraz.pk", "daraz.com",
    "etsy.com", "ebay.com", "aliexpress.com", "alibaba.com",
    "walmart.com", "target.com",
    "facebook.com", "instagram.com", "tiktok.com", "youtube.com", "pinterest.com",
    "netflix.com", "microsoft.com", "google.com", "yahoo.com"
]

def is_shopify_site(url: str, timeout: float = 10.0) -> Tuple[bool, Dict[str, Any]]:
    """
    Detects if a given website URL is running on Shopify.
    Returns (is_shopify: bool, details: dict).
    """
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    details = {
        "url": url,
        "is_shopify": False,
        "reasons": []
    }

    # 1. Domain Blacklist Pre-check
    try:
        parsed_url = urlparse(url)
        domain = parsed_url.netloc.lower().replace("www.", "")
        if any(m in domain for m in MARKETPLACE_BLACKLIST):
            details["reasons"].append(f"Domain is blacklisted: {domain}")
            return False, details
    except Exception:
        pass

    try:
        with httpx.Client(headers=DEFAULT_HEADERS, timeout=timeout, follow_redirects=True, verify=False) as client:
            resp = client.get(url)
            html = resp.text
            final_url = str(resp.url)
            details["final_url"] = final_url

            # Re-check final redirect URL against blacklist
            parsed_final = urlparse(final_url)
            final_domain = parsed_final.netloc.lower().replace("www.", "")
            if any(m in final_domain for m in MARKETPLACE_BLACKLIST):
                details["reasons"].append(f"Redirected domain is blacklisted: {final_domain}")
                return False, details

            # 2. Check CDN and Javascript Objects in HTML source
            if "cdn.shopify.com" in html:
                details["is_shopify"] = True
                details["reasons"].append("Found cdn.shopify.com in page source")

            if "window.Shopify" in html or "Shopify.theme" in html or "Shopify.designHost" in html:
                details["is_shopify"] = True
                details["reasons"].append("Found window.Shopify object in page source")

            if re.search(r'<meta[^>]+content=["\']Shopify["\']', html, re.I):
                details["is_shopify"] = True
                details["reasons"].append("Found Shopify meta generator tag")

            if "shopify-section" in html or "shopify-buy" in html:
                details["is_shopify"] = True
                details["reasons"].append("Found shopify CSS classes/sections")

            # 3. Probe endpoint /cart.json (with strict JSON content and key validation)
            if not details["is_shopify"]:
                try:
                    cart_url = final_url.rstrip("/") + "/cart.json"
                    cart_resp = client.get(cart_url)
                    # Check if response status is 200, is valid JSON, and has shopify specific cart keys
                    if cart_resp.status_code == 200:
                        cart_data = cart_resp.json()
                        if isinstance(cart_data, dict) and "token" in cart_data and "items" in cart_data:
                            details["is_shopify"] = True
                            details["reasons"].append("Successfully verified via /cart.json JSON parse check")
                except Exception:
                    pass

    except Exception as e:
        details["error"] = str(e)

    return details["is_shopify"], details


if __name__ == "__main__":
    import sys
    test_url = sys.argv[1] if len(sys.argv) > 1 else "https://gymshark.com"
    is_shopify, info = is_shopify_site(test_url)
    print(f"URL: {test_url} -> Shopify: {is_shopify}")
    print("Details:", info)
