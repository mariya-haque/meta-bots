import os
import sys
import json
import argparse
import re
from typing import List, Dict, Any
from urllib.parse import urlparse
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

# Ensure stdout uses UTF-8 on Windows console
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from meta_ad_scraper import scrape_meta_ads_browser, fetch_meta_ads_api
from shopify_detector import is_shopify_site
from contact_scraper import scrape_contact_info

# Predefined Categories requested by the User with simple, high-yield search terms
CATEGORIES_MAPPING = {
    "womens_clothing_abaya": {
        "name": "Women's Clothing & Abaya",
        "search_keywords": ["abaya", "stitched suits", "womens clothing"]
    },
    "mens_clothing_kurta": {
        "name": "Men's Clothing & Kurta",
        "search_keywords": ["kurta", "shalwar kameez", "mens clothing"]
    },
    "beauty_skincare_makeup": {
        "name": "Beauty, Skincare & Makeup",
        "search_keywords": ["beauty"]
    },
    "makeup": {
        "name": "Makeup",
        "search_keywords": ["makeup", "cosmetics"]
    },
    "skincare": {
        "name": "Skincare",
        "search_keywords": ["skincare", "serums"]
    },
    "jewelry_artificial": {
        "name": "Jewelry, Artificial & Imitation",
        "search_keywords": ["artificial jewelry", "imitation jewelry"]
    },
    "bags_purses": {
        "name": "Bags, Purses & Accessories",
        "search_keywords": ["handbags", "purses", "clutches"]
    },
    "footwear": {
        "name": "Footwear",
        "search_keywords": ["shoes", "footwear", "sandals"]
    },
    "mobile_accessories": {
        "name": "Mobile Accessories & Gadgets",
        "search_keywords": ["mobile accessories", "phone cases", "gadgets"]
    },
    "home_decor": {
        "name": "Home Decor & Kitchenware",
        "search_keywords": ["home decor", "kitchenware", "bedsheets"]
    },
    "baby_kids": {
        "name": "Baby & Kids Products",
        "search_keywords": ["baby products", "kids clothing", "toys"]
    },
    "health_wellness": {
        "name": "Health, Wellness & Herbal Supplements",
        "search_keywords": ["herbal supplements", "wellness products", "organic oil"]
    },
    "perfumes_attars": {
        "name": "Perfumes & Attars",
        "search_keywords": ["perfume", "attar", "fragrance"]
    },
    "bedsheets_linen": {
        "name": "Bedsheets, Linen & Home Textiles",
        "search_keywords": ["bedsheets", "cushions", "curtains"]
    },
    "watches": {
        "name": "Watches",
        "search_keywords": ["watches", "smartwatches"]
    },
    "fitness_gym": {
        "name": "Fitness & Gym Accessories",
        "search_keywords": ["gym accessories", "activewear", "fitness gear"]
    }
}

def export_to_excel(leads: List[Dict[str, Any]], filepath: str):
    """
    Exports a list of lead dictionaries into a formatted Excel (.xlsx) file.
    Handles PermissionError gracefully (if the file is open in Excel).
    """
    if not leads:
        # Save an empty sheet with columns for consistency
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
        print(f"📊 Excel Exported: {filepath}")
    except PermissionError:
        # Fallback to copy name if file is open in MS Excel
        fallback_path = filepath.replace(".xlsx", "_copy.xlsx")
        print(f"[!] Warning: '{filepath}' is open in Excel and locked. Saving copy to '{fallback_path}' instead.")
        try:
            df.to_excel(fallback_path, index=False)
        except Exception as e:
            print(f"[!] Failed to write Excel copy: {e}")
    except Exception as e:
        print(f"[!] Failed to write Excel file: {e}")

def run_automation(selected_categories: List[str] = None, country: str = "PK", max_ads_per_keyword: int = 50, access_token: str = None) -> List[Dict[str, Any]]:
    all_shopify_leads = []
    processed_domains = set()  # Global deduplication to prevent repetitions/duplicates

    # Output folder setup
    output_dir = "leads"
    os.makedirs(output_dir, exist_ok=True)

    # Use all predefined categories if none is specifically provided
    categories_to_run = selected_categories if selected_categories else list(CATEGORIES_MAPPING.keys())

    # Fallback to env token if not passed directly
    if not access_token:
        access_token = os.getenv("META_ACCESS_TOKEN", "").strip() or None

    print("=" * 70)
    print("🚀 META AD LIBRARY TO SHOPIFY LEAD GENERATION & EXCEL CRAWLER")
    print(f"[*] Target Country: {country} (Pakistani phone numbers only)")
    print(f"[*] Max Ads Scanned Per Category: {max_ads_per_keyword}")
    print(f"[*] Access Method: {'Official Meta API' if access_token else 'Playwright Stealth Browser'}")
    print(f"[*] Leads Output Directory: {os.path.abspath(output_dir)}")
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
        ads_per_kw = max(3, max_ads_per_keyword // len(keywords_list))

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

            # Parse domain to prevent duplicate crawling globally
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

            print(f"   ✅ SHOPIFY CONFIRMED! ({', '.join(details.get('reasons', []))})")
            print(f"   🔍 Extracting contact info & store details...")

            # 3. Extract store details and contact info
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
            print(f"   🎉 Lead Saved [{cat_name}]: {lead['website_name']} | Emails: {emails} | Phones: {phones}")

        # Step 1: Save Category specific JSON File
        json_file = os.path.join(output_dir, f"{cat_key}_leads.json")
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(category_leads, f, indent=2, ensure_ascii=False)

        # Step 2: Save Category specific Excel (.xlsx) File
        xlsx_file = os.path.join(output_dir, f"{cat_key}_leads.xlsx")
        export_to_excel(category_leads, xlsx_file)

        print(f"📁 Category '{cat_name}' Complete. Saved {len(category_leads)} leads.")

    # Save Consolidated Master JSON & Excel Files
    master_json = os.path.join(output_dir, "all_shopify_leads.json")
    with open(master_json, "w", encoding="utf-8") as f:
        json.dump(all_shopify_leads, f, indent=2, ensure_ascii=False)

    master_xlsx = os.path.join(output_dir, "all_shopify_leads.xlsx")
    export_to_excel(all_shopify_leads, master_xlsx)

    print("\n" + "=" * 70)
    print(f"✅ COMPLETE PIPELINE RUN FINISHED!")
    print(f"📄 Total Unique Leads Extracted: {len(all_shopify_leads)}")
    print(f"📁 Folder Location: {os.path.abspath(output_dir)}")
    print("=" * 70)

    return all_shopify_leads

if __name__ == "__main__":
    env_country = os.getenv("DEFAULT_COUNTRY", "PK")
    env_max_ads = int(os.getenv("MAX_ADS_PER_KEYWORD", "50"))

    parser = argparse.ArgumentParser(description="Meta Ad Library to Shopify Lead Extractor")
    parser.add_argument("--categories", type=str, default=None, help="Comma-separated category keys (e.g. womens_clothing_abaya,watches)")
    parser.add_argument("--country", type=str, default=env_country, help="Target country code (e.g. PK)")
    parser.add_argument("--max_ads", type=int, default=env_max_ads, help="Max ads to check per category")
    parser.add_argument("--token", type=str, default=None, help="Meta Graph API Access Token (Optional)")

    args = parser.parse_args()
    
    selected_cats = None
    if args.categories:
        selected_cats = [c.strip() for c in args.categories.split(",") if c.strip()]

    run_automation(selected_cats, country=args.country, max_ads_per_keyword=args.max_ads, access_token=args.token)
