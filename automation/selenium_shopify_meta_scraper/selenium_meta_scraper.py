import os
import time
import re
import urllib.parse
from typing import List, Dict, Any

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
from dotenv import load_dotenv

load_dotenv()

def normalize_country(country: str) -> str:
    c = country.strip().upper()
    if c in ["PAKISTAN", "PAK", "PK"]:
        return "PK"
    if c in ["UNITED STATES", "USA", "US"]:
        return "US"
    return c

def scrape_meta_ads_browser(keyword: str, country: str = "PK", max_ads: int = 20) -> List[Dict[str, Any]]:
    """
    Searches Meta Ad Library using Selenium automated Chrome browser.
    Extracts destination landing pages from ad cards.
    """
    iso_country = normalize_country(country)
    encoded_keyword = urllib.parse.quote(keyword)
    url = f"https://www.facebook.com/ads/library/?active_status=all&ad_type=all&country={iso_country}&q={encoded_keyword}&search_type=keyword_unordered"
    
    ads_data = []
    is_headless = os.getenv("HEADLESS_MODE", "true").lower() == "true"

    chrome_options = Options()
    chrome_options.page_load_strategy = "eager"
    if is_headless:
        chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)

    print(f"[*] Starting Selenium Chrome (Headless={is_headless}) for keyword: '{keyword}'...")
    
    driver = None
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        # Selenium Stealth-like settings
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """
        })
        
        driver.get(url)
        time.sleep(5)  # Wait for page to initialize

        # Perform scrolling to load more ads
        scroll_rounds = max(4, max_ads // 5)
        print(f"[*] Scrolling Ad Library page {scroll_rounds} times...")
        for r in range(scroll_rounds):
            driver.execute_script("window.scrollBy(0, 2000);")
            time.sleep(2.5)

        # Scrape all anchor elements with links
        elements = driver.find_elements(By.TAG_NAME, "a")
        extracted_urls = set()

        for elem in elements:
            try:
                href = elem.get_attribute("href")
                if not href:
                    continue
                
                # Check for Facebook redirect links
                if "facebook.com" in href and "l.facebook.com/l.php" in href:
                    parsed = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                    if "u" in parsed:
                        target_url = parsed["u"][0]
                        if not any(x in target_url for x in ["facebook.com", "instagram.com"]):
                            extracted_urls.add(target_url)
                elif not any(x in href for x in ["facebook.com", "fb.me", "javascript:", "#", "instagram.com"]):
                    if href.startswith("http"):
                        extracted_urls.add(href)
            except Exception:
                pass

        print(f"[+] Found {len(extracted_urls)} outbound URLs in page source.")
        for target_url in list(extracted_urls)[:max_ads]:
            ads_data.append({
                "keyword": keyword,
                "destination_url": target_url,
                "source": "Meta Ad Library Selenium Scraper"
            })

    except Exception as e:
        print(f"[!] Error in Selenium Meta Ad Scraper: {e}")
    finally:
        if driver:
            driver.quit()

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
    # Quick standalone test execution
    results = scrape_meta_ads_browser("makeup", max_ads=5)
    print("Extracted Ads:", results)
