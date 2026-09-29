import httpx
import re
from bs4 import BeautifulSoup
from typing import Dict, Any, List, Set
from urllib.parse import urljoin, urlparse

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

EMAIL_REGEX = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
# Strict Pakistani Phone regex: matches 03xx-xxxxxxx, +92-3xx-xxxxxxx, 021-xxxxxxx, etc.
PK_MOBILE_REGEX = re.compile(r'(?:\+?92[-.\s]?3|03)\d{2}[-.\s]?\d{7}\b')
PK_LANDLINE_REGEX = re.compile(r'(?:\+?92[-.\s]?(?:21|42|51|41|61|81|91)|0(?:21|42|51|41|61|81|91))[-.\s]?\d{7,8}\b')

# 32-bit Integer Overflow values commonly used as theme database placeholders
BANNED_NUMBERS = {"2147483647", "47483647", "2147483648", "9999999999", "1234567890", "0000000000"}

IGNORED_EMAIL_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.css', '.js', 'sentry.io', 'wixpress.com')

def clean_emails(emails: Set[str]) -> List[str]:
    valid = set()
    for email in emails:
        email_lower = email.lower()
        if not any(email_lower.endswith(ext) or ext in email_lower for ext in IGNORED_EMAIL_EXTENSIONS):
            valid.add(email)
    return list(valid)

def filter_pakistani_phones(phones: Set[str]) -> List[str]:
    valid_pk_phones = set()
    for phone in phones:
        # Strip all whitespace, dashes, brackets, and leading plus sign for format validation
        cleaned = re.sub(r'[\s\-\(\)\+]', '', phone)
        
        # Check if the number is a known database placeholder/constant
        if any(banned in cleaned for banned in BANNED_NUMBERS):
            continue

        # Mobile check (11 or 12 digits: e.g. 03001234567, 923001234567)
        if re.match(r'^(?:92|0)?3\d{9}$', cleaned):
            if cleaned.startswith('92'):
                valid_pk_phones.add("+" + cleaned)
            elif cleaned.startswith('0'):
                valid_pk_phones.add("+92" + cleaned[1:])
            else:
                # 3xx format (10 digits)
                valid_pk_phones.add("+92" + cleaned)
        # Landline check (e.g. 02112345678, 922112345678)
        elif re.match(r'^(?:92|0)?(?:21|42|51|41|61|81|91)\d{7,8}$', cleaned):
            if cleaned.startswith('92'):
                valid_pk_phones.add("+" + cleaned)
            elif cleaned.startswith('0'):
                valid_pk_phones.add("+92" + cleaned[1:])
            else:
                valid_pk_phones.add("+92" + cleaned)
    return list(valid_pk_phones)

def extract_store_name(soup: BeautifulSoup, fallback_url: str) -> str:
    # 1. Try og:site_name
    og_site = soup.find("meta", property="og:site_name")
    if og_site and og_site.get("content"):
        return og_site["content"].strip()
    
    # 2. Try window.Shopify.shop
    script_tags = soup.find_all("script")
    for script in script_tags:
        if script.string and "Shopify.shop" in script.string:
            match = re.search(r'Shopify\.shop\s*=\s*["\']([^"\']+)["\']', script.string)
            if match:
                return match.group(1).replace('.myshopify.com', '').replace('-', ' ').title()

    # 3. Try page title
    title = soup.find("title")
    if title and title.string:
        clean_title = title.string.split("|")[0].split("-")[0].strip()
        if len(clean_title) > 1:
            return clean_title

    # 4. Fallback to domain name
    parsed = urlparse(fallback_url)
    return parsed.netloc.replace("www.", "").split(".")[0].capitalize()


def scrape_contact_info(url: str, timeout: float = 12.0) -> Dict[str, Any]:
    """
    Crawls homepage and contact pages to extract Store Name, Emails, Phone numbers, and Instagram profile.
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
    instagram_link: str = None
    store_name: str = ""

    pages_to_crawl = [url]
    crawled_urls: Set[str] = set()

    with httpx.Client(headers=DEFAULT_HEADERS, timeout=timeout, follow_redirects=True, verify=False) as client:
        # Step 1: Fetch Homepage
        try:
            resp = client.get(url)
            crawled_urls.add(str(resp.url))
            result["scraped_pages"].append(str(resp.url))
            html = resp.text
            soup = BeautifulSoup(html, "lxml")

            store_name = extract_store_name(soup, url)

            # Find Emails & Phones on homepage
            found_emails.update(EMAIL_REGEX.findall(html))
            found_phones.update(PK_MOBILE_REGEX.findall(html))
            found_phones.update(PK_LANDLINE_REGEX.findall(html))

            # Find Instagram link
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "instagram.com" in href and not instagram_link:
                    instagram_link = href

                # Discover contact/about page links
                href_lower = href.lower()
                if any(k in href_lower for k in ["contact", "about", "reach-us", "get-in-touch"]):
                    full_link = urljoin(url, href)
                    if full_link not in pages_to_crawl and full_link not in crawled_urls:
                        pages_to_crawl.append(full_link)

        except Exception as e:
            result["error"] = f"Failed to fetch homepage: {str(e)}"

        # Step 2: Crawl Contact/About pages (up to 3 additional pages)
        for page_url in pages_to_crawl[1:4]:
            if page_url in crawled_urls:
                continue
            try:
                resp = client.get(page_url)
                crawled_urls.add(str(resp.url))
                result["scraped_pages"].append(str(resp.url))
                html = resp.text
                soup = BeautifulSoup(html, "lxml")

                found_emails.update(EMAIL_REGEX.findall(html))
                found_phones.update(PK_MOBILE_REGEX.findall(html))
                found_phones.update(PK_LANDLINE_REGEX.findall(html))

                if not instagram_link:
                    for a in soup.find_all("a", href=True):
                        if "instagram.com" in a["href"]:
                            instagram_link = a["href"]
                            break
            except Exception:
                pass

    result["store_name"] = store_name
    result["emails"] = clean_emails(found_emails)
    result["phones"] = filter_pakistani_phones(found_phones)[:3]  # keep top 3 PK numbers
    result["instagram"] = instagram_link

    return result

if __name__ == "__main__":
    import sys
    test_url = sys.argv[1] if len(sys.argv) > 1 else "https://gymshark.com"
    data = scrape_contact_info(test_url)
    print("Scraped Data:", data)
