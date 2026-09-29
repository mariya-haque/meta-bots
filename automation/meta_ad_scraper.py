import os
import time
import re
import urllib.parse
from typing import List, Dict, Any
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

load_dotenv()

def normalize_country(country: str) -> str:
    c = country.strip().upper()
    if c in ["PAKISTAN", "PAK", "PK"]:
        return "PK"
    if c in ["UNITED STATES", "USA", "US"]:
        return "US"
    return c

def scrape_meta_ads_browser(keyword: str, country: str = "PK", max_ads: int = 50) -> List[Dict[str, Any]]:
    """
    Searches Meta Ad Library using headless/headed browser automation via Playwright.
    Extracts ad card info, advertiser page name, Instagram link, and destination website URL.
    """
    iso_country = normalize_country(country)
    encoded_keyword = urllib.parse.quote(keyword)
    url = f"https://www.facebook.com/ads/library/?active_status=all&ad_type=all&country={iso_country}&q={encoded_keyword}&search_type=keyword_unordered"
    
    ads_data = []

    # Read headless mode and proxy settings from env
    is_headless = os.getenv("HEADLESS_MODE", "true").lower() == "true"
    proxy_url = os.getenv("PROXY_URL", "").strip()

    launch_args = [
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-blink-features=AutomationControlled"
    ]

    proxy_config = {"server": proxy_url} if proxy_url else None

    with sync_playwright() as p:
        # Launch browser in stealth mode
        browser = p.chromium.launch(
            headless=is_headless,
            args=launch_args,
            proxy=proxy_config
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900}
        )
        page = context.new_page()

        print(f"[*] Navigating to Meta Ad Library for keyword: '{keyword}' (Country: {iso_country}, Headless: {is_headless})...")
        try:
            page.goto(url, wait_until="networkidle", timeout=35000)
            time.sleep(4)

            # Deeper scroll down to load maximum available ad cards
            scroll_rounds = max(5, max_ads // 5)
            for r in range(scroll_rounds):
                page.mouse.wheel(0, 2000)
                time.sleep(2)

            # Find links and external destination buttons/links in ad cards
            link_elements = page.query_selector_all("a[href]")

            extracted_urls = set()

            for elem in link_elements:
                try:
                    href = elem.get_attribute("href")
                    if not href:
                        continue
                    
                    # Filter out Facebook internal navigation links
                    if "facebook.com" in href and "l.facebook.com/l.php" in href:
                        # Extract redirect target URL from Facebook link shim (l.php?u=...)
                        parsed = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                        if "u" in parsed:
                            target_url = parsed["u"][0]
                            if not any(x in target_url for x in ["facebook.com", "instagram.com"]):
                                extracted_urls.add(target_url)

                    elif not any(x in href for x in ["facebook.com", "fb.me", "javascript:", "#"]):
                        if href.startswith("http"):
                            extracted_urls.add(href)
                except Exception:
                    pass

            for target_url in list(extracted_urls)[:max_ads]:
                ads_data.append({
                    "keyword": keyword,
                    "destination_url": target_url,
                    "source": "Meta Ad Library Browser Scraper"
                })

        except Exception as e:
            print(f"[!] Error scraping Meta Ad Library browser UI: {e}")
        finally:
            browser.close()

    return ads_data

def fetch_meta_ads_api(keyword: str, access_token: str, country: str = "PK", max_ads: int = 50) -> List[Dict[str, Any]]:
    """
    Fetches ads using the Official Meta Graph API / Ad Library API if an access token is provided.
    """
    import httpx
    iso_country = normalize_country(country)
    api_url = "https://graph.facebook.com/v18.0/ads_archive"
    params = {
        "access_token": access_token,
        "search_terms": keyword,
        "ad_reached_countries": f"['{iso_country}']",
        "ad_active_status": "ALL",
        "ad_type": "ALL",
        "fields": "id,page_id,page_name,ad_snapshot_url,ad_creative_bodies,ad_creative_link_captions,ad_creative_link_titles",
        "limit": max_ads
    }
    
    ads = []
    try:
        resp = httpx.get(api_url, params=params, timeout=15.0)
        data = resp.json()
        if "error" in data:
            print(f"[!] Meta API Error Response: {data['error'].get('message')}")
        if "data" in data:
            for item in data["data"]:
                # Check for direct link_url or extracted link captions
                link_url = item.get("link_url") or item.get("ad_creative_link_captions", [None])[0]
                if link_url:
                    if not link_url.startswith(("http://", "https://")):
                        link_url = "https://" + link_url
                    ads.append({
                        "keyword": keyword,
                        "ad_id": item.get("id"),
                        "page_name": item.get("page_name"),
                        "destination_url": link_url,
                        "source": "Meta Graph API"
                    })
    except Exception as e:
        print(f"[!] API Network Exception: {e}")

    return ads

if __name__ == "__main__":
    results = scrape_meta_ads_browser("makeup", max_ads=5)
    print("Extracted Ads:", results)
