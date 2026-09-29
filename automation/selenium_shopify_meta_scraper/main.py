import os
import sys
import json
import argparse
from typing import List, Dict, Any
from urllib.parse import urlparse
import pandas as pd
from dotenv import load_dotenv

# Ensure stdout uses UTF-8 on Windows console
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Resolve absolute imports relative to this script directory
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

from selenium_meta_scraper import scrape_meta_ads_browser, fetch_meta_ads_api
from shopify_detector import is_shopify_site
from selenium_contact_scraper import scrape_contact_info

load_dotenv(os.path.join(script_dir, ".env"))

# 14 Categories mapping requested by the user, with high-intent keywords for Pakistan
CATEGORIES_MAPPING = {
    "womens_clothing_abaya": {
        "name": "Women's clothing and abaya/stitched suits",
        "search_keywords": ["abaya pakistan", "stitched suits pk", "womens clothing pakistan"]
    },
    "mens_clothing_kurta": {
        "name": "Men's clothing and kurta/shalwar kameez",
        "search_keywords": ["mens kurta pk", "shalwar kameez pakistan", "mens wear pakistan"]
    },
    "beauty_skincare_makeup": {
        "name": "Beauty, skincare, and makeup",
        "search_keywords": ["skincare pakistan", "makeup brand pakistan", "cosmetics pk"]
    },
    "jewelry_artificial": {
        "name": "Jewelry, artificial and imitation",
        "search_keywords": ["artificial jewelry pakistan", "imitation jewelry pk", "silver jewelry pk"]
    },
    "bags_purses": {
        "name": "Bags, purses, and accessories",
        "search_keywords": ["handbags pakistan", "womens purses pk", "clutches pakistan"]
    },
    "footwear": {
        "name": "Footwear",
        "search_keywords": ["shoes pakistan", "khussa online pk", "footwear pakistan"]
    },
    "mobile_accessories": {
        "name": "Mobile accessories and gadgets",
        "search_keywords": ["mobile accessories pakistan", "phone cases pk", "gadgets pakistan"]
    },
    "home_decor": {
        "name": "Home decor and kitchenware",
        "search_keywords": ["home decor pakistan", "kitchenware pk", "home accessories pk"]
    },
    "baby_kids": {
        "name": "Baby and kids products",
        "search_keywords": ["baby clothing pakistan", "kids toys pk", "baby products pk"]
    },
    "health_wellness": {
        "name": "Health, wellness, and herbal/supplements",
        "search_keywords": ["herbal supplements pakistan", "organic honey pk", "wellness products pakistan"]
    },
    "perfumes_attars": {
        "name": "Perfumes and attars",
        "search_keywords": ["perfume pakistan", "attar online pk", "fragrances pk"]
    },
    "bedsheets_linen": {
        "name": "Bedsheets, linen, and home textiles",
        "search_keywords": ["bedsheets pakistan", "linen bedding pk", "home textiles pk"]
    },
    "watches": {
        "name": "Watches",
        "search_keywords": ["watches pakistan", "smartwatch pk", "luxury watches pk"]
    },
    "fitness_gym": {
        "name": "Fitness and gym accessories",
        "search_keywords": ["gym wear pakistan", "activewear pk", "fitness accessories pk"]
    }
}

def export_to_excel(leads: List[Dict[str, Any]], filepath: str):
    """
    Exports a list of lead dictionaries into a formatted Excel (.xlsx) file.
    """
    if not leads:
        df = pd.DataFrame(columns=["Category", "Store Name", "Website Link", "Emails", "Phones", "Instagram"])
    else:
        rows = []
        for lead in leads:
            rows.append({
                "Category": lead.get("category_name"),
                "Store Name": lead.get("website_name"),
                "Website Link": lead.get("website_link"),
                "Emails": ", ".join(lead.get("contact_info", {}).get("emails", [])),
                "Phones": ", ".join(lead.get("contact_info", {}).get("phones", [])),
                "Instagram": lead.get("contact_info", {}).get("instagram", "") or ""
            })
        df = pd.DataFrame(rows)

    try:
        df.to_excel(filepath, index=False)
        print(f"   📊 Excel Exported: {filepath}")
    except PermissionError:
        fallback_path = filepath.replace(".xlsx", "_copy.xlsx")
        print(f"   [!] Warning: '{filepath}' is locked. Saving to '{fallback_path}' instead.")
        try:
            df.to_excel(fallback_path, index=False)
        except Exception as e:
            print(f"   [!] Failed to write Excel copy: {e}")
    except Exception as e:
        print(f"   [!] Failed to write Excel file: {e}")

def run_pipeline(selected_categories: List[str] = None, country: str = "PK", max_ads_per_keyword: int = 15, access_token: str = None) -> List[Dict[str, Any]]:
    all_shopify_leads = []
    processed_domains = set()  # Global deduplication to prevent double-crawling

    # Setup leads output directory
    output_dir = os.path.join(script_dir, "leads")
    os.makedirs(output_dir, exist_ok=True)

    # Use all predefined categories if none are specifically selected
    categories_to_run = selected_categories if selected_categories else list(CATEGORIES_MAPPING.keys())

    # Fallback to env token if not passed directly
    if not access_token:
        access_token = os.getenv("META_ACCESS_TOKEN", "").strip() or None

    print("=" * 70)
    print("🚀 STARTING SELENIUM SHOPIFY LEAD GENERATION AUTOMATION")
    print(f"[*] Target Country: {country} (Filter: Pakistani Phone Numbers)")
    print(f"[*] Max Ads Scanned Per Category: {max_ads_per_keyword}")
    print(f"[*] Mode: {'Official API + Selenium Fallback' if access_token else 'Strict Selenium Browser Scraper'}")
    print(f"[*] Output Directory: {output_dir}")
    print("=" * 70)

    for cat_key in categories_to_run:
        if cat_key not in CATEGORIES_MAPPING:
            print(f"[!] Unknown category key '{cat_key}'. Skipping.")
            continue

        cat_info = CATEGORIES_MAPPING[cat_key]
        cat_name = cat_info["name"]
        keywords_list = cat_info["search_keywords"]
        category_leads = []

        print(f"\n📂 CATEGORY: {cat_name} (Keywords: {', '.join(keywords_list)})")
        
        ads = []
        # Calculate limit per keyword in this category
        ads_per_kw = max(2, max_ads_per_keyword // len(keywords_list))

        for kw in keywords_list:
            print(f"   🔎 Searching keyword: '{kw}'...")
            kw_ads = []
            if access_token:
                kw_ads = fetch_meta_ads_api(kw, access_token, country=country, max_ads=ads_per_kw)
                if not kw_ads:
                    kw_ads = scrape_meta_ads_browser(kw, country=country, max_ads=ads_per_kw)
            else:
                kw_ads = scrape_meta_ads_browser(kw, country=country, max_ads=ads_per_kw)
            
            ads.extend(kw_ads)

        print(f"[+] Total ads collected for category '{cat_name}': {len(ads)} links.")

        for idx, ad in enumerate(ads, 1):
            dest_url = ad.get("destination_url")
            if not dest_url:
                continue

            parsed_url = urlparse(dest_url)
            domain = parsed_url.netloc.lower().replace("www.", "")
            if not domain or domain in processed_domains:
                continue
            
            processed_domains.add(domain)
            print(f"\n   [{idx}/{len(ads)}] Checking Website: {dest_url}")

            # 2. Check if website is Shopify based
            is_shopify, details = is_shopify_site(dest_url)
            if not is_shopify:
                print(f"   ❌ Not a Shopify website. Skipping.")
                continue

            print(f"   ✅ Shopify Confirmed! ({', '.join(details.get('reasons', []))})")
            print(f"   🔍 Extracting contact info using Selenium...")

            # 3. Extract store details and contact info using Selenium
            contact_data = scrape_contact_info(dest_url)

            # Skip stores that have no email AND no phone (prevents junk leads)
            emails = contact_data.get("emails", [])
            phones = contact_data.get("phones", [])
            
            lead = {
                "category_key": cat_key,
                "category_name": cat_name,
                "website_name": contact_data.get("store_name"),
                "website_link": dest_url,
                "is_shopify": True,
                "contact_info": {
                    "emails": emails,
                    "phones": phones,
                    "instagram": contact_data.get("instagram")
                },
                "scraped_pages": contact_data.get("scraped_pages", [])
            }

            category_leads.append(lead)
            all_shopify_leads.append(lead)
            print(f"   🎉 Lead Saved [{cat_name}]: {lead['website_name']}")
            print(f"      - Emails: {emails}")
            print(f"      - Verified Phones: {phones}")

        # Save Category specific JSON File
        json_file = os.path.join(output_dir, f"{cat_key}_leads.json")
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(category_leads, f, indent=2, ensure_ascii=False)

        # Save Category specific Excel File
        xlsx_file = os.path.join(output_dir, f"{cat_key}_leads.xlsx")
        export_to_excel(category_leads, xlsx_file)

        print(f"📁 Category '{cat_name}' complete. Saved {len(category_leads)} leads.")

    # Save Consolidated Master JSON & Excel Files
    master_json = os.path.join(output_dir, "all_shopify_leads.json")
    with open(master_json, "w", encoding="utf-8") as f:
        json.dump(all_shopify_leads, f, indent=2, ensure_ascii=False)

    master_xlsx = os.path.join(output_dir, "all_shopify_leads.xlsx")
    export_to_excel(all_shopify_leads, master_xlsx)

    print("\n" + "=" * 70)
    print(f"✅ PIPELINE EXECUTION COMPLETED!")
    print(f"📄 Total Unique Leads Extracted: {len(all_shopify_leads)}")
    print(f"📁 Leads folder: {output_dir}")
    print("=" * 70)

    return all_shopify_leads

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Selenium-based Meta Ad Library to Shopify Lead Extractor")
    parser.add_argument("--categories", type=str, default=None, help="Comma-separated category keys (e.g. watches,footwear)")
    parser.add_argument("--country", type=str, default="PK", help="Target country code (e.g. PK)")
    parser.add_argument("--max_ads", type=int, default=15, help="Max ads to check per category")
    parser.add_argument("--token", type=str, default=None, help="Meta Graph API Access Token (Optional)")

    args = parser.parse_args()
    
    selected_cats = None
    if args.categories:
        selected_cats = [c.strip() for c in args.categories.split(",") if c.strip()]

    run_pipeline(selected_cats, country=args.country, max_ads_per_keyword=args.max_ads, access_token=args.token)
