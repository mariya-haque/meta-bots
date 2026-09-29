import os
import re
import time
from typing import Dict, Any, List, Set
from urllib.parse import urljoin, urlparse

import phonenumbers
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

# Basic configurations
EMAIL_REGEX = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')

# Regex to match potential Pakistani phone candidates for validation
PK_PHONE_CANDIDATE_REGEX = re.compile(r'(?:\+?92[-.\s]?3|03)\d{2}[-.\s]?\d{7}\b|(?:\+?92[-.\s]?(?:21|42|51|41|61|81|91)|0(?:21|42|51|41|61|81|91))[-.\s]?\d{7,8}\b')

# 32-bit Integer Overflow values commonly used as theme database placeholders or fake numbers
BANNED_NUMBERS = {"2147483647", "47483647", "2147483648", "9999999999", "1234567890", "0000000000"}
IGNORED_EMAIL_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.css', '.js', 'sentry.io', 'wixpress.com')
IGNORED_EMAIL_DOMAINS = {
    'shopify.com', 'example.com', 'stagheaddesigns.com', 'presathemes.com',
    'halothemes.com', 'pixelunion.net', 'outofthesandbox.com', 'flycart.org',
    'theme.com', 'wixpress.com', 'sentry.io'
}

def clean_emails(emails: Set[str]) -> List[str]:
    valid = set()
    for email in emails:
        if not email or not isinstance(email, str):
            continue
        email = email.strip()
        if not email:
            continue
        email_lower = email.lower()
        if not any(email_lower.endswith(ext) or ext in email_lower for ext in IGNORED_EMAIL_EXTENSIONS):
            # Extract domain part to filter theme developer emails
            parts = email_lower.split('@')
            if len(parts) == 2:
                domain = parts[1]
                if domain not in IGNORED_EMAIL_DOMAINS:
                    valid.add(email)
            else:
                valid.add(email)
    return list(valid)

def verify_and_format_pk_phone(phone_str: str) -> str:
    """
    Parses and verifies if a phone number candidate is a valid Pakistani phone number.
    Returns the E.164 formatted number (+923xxxxxxxxx) if valid, otherwise None.
    """
    try:
        # Strip brackets, spaces, and dashes for safety
        cleaned = re.sub(r'[\s\-\(\)\+]', '', phone_str)
        # Check against banned constants
        if any(banned in cleaned for banned in BANNED_NUMBERS):
            return None

        # Parse with phonenumbers (specifying PK region)
        parsed = phonenumbers.parse(phone_str, "PK")
        if phonenumbers.is_valid_number(parsed) and phonenumbers.is_possible_number(parsed):
            # Strict verification of the country prefix code for Pakistan (+92)
            if parsed.country_code == 92:
                # Format to E.164 format (+92XXXXXXXXXX)
                return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except Exception:
        pass
    return None

def filter_pakistani_phones(candidates: Set[str]) -> List[str]:
    valid_pk_phones = set()
    for cand in candidates:
        formatted = verify_and_format_pk_phone(cand)
        if formatted:
            valid_pk_phones.add(formatted)
    return list(valid_pk_phones)

def extract_store_name_selenium(driver) -> str:
    # 1. Try Shopify global object via Javascript execution
    try:
        shop_domain = driver.execute_script("return window.Shopify ? window.Shopify.shop : null;")
        if shop_domain:
            return shop_domain.replace('.myshopify.com', '').replace('-', ' ').replace('_', ' ').title()
    except Exception:
        pass

    # 2. Try og:site_name meta tag
    try:
        meta_elem = driver.find_element(By.XPATH, "//meta[@property='og:site_name']")
        name = meta_elem.get_attribute("content")
        if name:
            return name.strip()
    except Exception:
        pass

    # 3. Try HTML Title tag
    try:
        title = driver.title
        if title:
            clean_title = title.split("|")[0].split("-")[0].strip()
            if len(clean_title) > 1:
                return clean_title
    except Exception:
        pass

    # 4. Fallback to domain name
    try:
        parsed = urlparse(driver.current_url)
        return parsed.netloc.replace("www.", "").split(".")[0].capitalize()
    except Exception:
        return "Unknown Shop"

def scrape_contact_info(url: str, timeout: float = 20.0) -> Dict[str, Any]:
    """
    Loads the store homepage and contact pages using a headless Selenium instance,
    extracting Shopify store name, emails, Pakistani phone numbers, and Instagram link.
    """
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    result = {
        "website_url": url,
        "store_name": "",
        "emails": [],
        "phones": [],
        "instagram": None,
        "scraped_pages": []
    }

    found_emails: Set[str] = set()
    found_phones: Set[str] = set()
    instagram_link = None
    store_name = ""

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
    
    driver = None
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.set_page_load_timeout(timeout)

        # 1. Load Homepage
        print(f"   [*] Loading homepage: {url}")
        driver.get(url)
        time.sleep(4)  # Wait for scripts to execute and load page DOM

        result["scraped_pages"].append(driver.current_url)
        page_source = driver.page_source

        # Extract name
        store_name = extract_store_name_selenium(driver)

        # Extract Emails & Phones from Page Source text
        found_emails.update(EMAIL_REGEX.findall(page_source))
        found_phones.update(PK_PHONE_CANDIDATE_REGEX.findall(page_source))

        # Check explicitly for mailto: and tel: links
        links = driver.find_elements(By.TAG_NAME, "a")
        contact_page_urls = set()

        for link in links:
            try:
                href = link.get_attribute("href")
                if not href:
                    continue
                
                # Check tel protocol
                if href.startswith("tel:"):
                    raw_num = href.replace("tel:", "").strip()
                    found_phones.add(raw_num)
                
                # Check mailto protocol
                elif href.startswith("mailto:"):
                    raw_email = href.replace("mailto:", "").strip()
                    # Strip any query parameters e.g. ?subject=...
                    raw_email = raw_email.split("?")[0]
                    found_emails.add(raw_email)
                
                # Check Instagram link
                elif "instagram.com" in href and not instagram_link:
                    instagram_link = href

                # Discover contact / about page paths
                href_lower = href.lower()
                if any(k in href_lower for k in ["contact", "about", "reach-us", "get-in-touch", "pages/contact", "support"]):
                    # Resolve relative links
                    full_link = urljoin(url, href)
                    if full_link != url and urlparse(full_link).netloc == urlparse(url).netloc:
                        contact_page_urls.add(full_link)
            except Exception:
                pass

        # 2. Visit discovered Contact / About pages (max 2 pages to save resources)
        for contact_url in list(contact_page_urls)[:2]:
            print(f"   [*] Navigating to discovered page: {contact_url}")
            try:
                driver.get(contact_url)
                time.sleep(3)
                result["scraped_pages"].append(driver.current_url)
                
                inner_source = driver.page_source
                found_emails.update(EMAIL_REGEX.findall(inner_source))
                found_phones.update(PK_PHONE_CANDIDATE_REGEX.findall(inner_source))

                # Check tel/mailto links on contact page
                inner_links = driver.find_elements(By.TAG_NAME, "a")
                for il in inner_links:
                    try:
                        ihref = il.get_attribute("href")
                        if not ihref:
                            continue
                        if ihref.startswith("tel:"):
                            found_phones.add(ihref.replace("tel:", "").strip())
                        elif ihref.startswith("mailto:"):
                            found_emails.add(ihref.replace("mailto:", "").strip().split("?")[0])
                        elif "instagram.com" in ihref and not instagram_link:
                            instagram_link = ihref
                    except Exception:
                        pass
            except Exception as e:
                print(f"   [!] Failed loading contact page {contact_url}: {e}")

    except Exception as e:
        print(f"   [!] Contact Scraping Error for {url}: {e}")
        result["error"] = str(e)
    finally:
        if driver:
            driver.quit()

    result["store_name"] = store_name
    result["emails"] = clean_emails(found_emails)
    result["phones"] = filter_pakistani_phones(found_phones)[:3]  # Keep top 3 verified PK numbers
    result["instagram"] = instagram_link

    return result

if __name__ == "__main__":
    import sys
    test_url = sys.argv[1] if len(sys.argv) > 1 else "https://www.hopkicks.pk"
    print("Testing contact scraping on URL:", test_url)
    res = scrape_contact_info(test_url)
    print("Scrape Result:", res)
