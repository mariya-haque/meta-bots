import os
import sys
import json
import argparse
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

load_dotenv(os.path.join(script_dir, ".env"))

# 14 Categories mapping requested by the user
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

def export_links_to_excel(leads: List[Dict[str, Any]], filepath: str):
    """
    Exports website links to a formatted Excel file.
    """
    if not leads:
        df = pd.DataFrame(columns=["Category", "Website Link", "Domain"])
    else:
        rows = []
        for lead in leads:
            rows.append({
                "Category": lead.get("category_name"),
                "Website Link": lead.get("website_link"),
                "Domain": lead.get("domain")
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

def run_link_extraction(selected_categories: List[str] = None, country: str = "PK", max_ads_per_keyword: int = 100, access_token: str = None):
    all_shopify_links = []
    processed_domains = set()

    output_dir = os.path.join(script_dir, "leads_links_only")
    os.makedirs(output_dir, exist_ok=True)

    categories_to_run = selected_categories if selected_categories else list(CATEGORIES_MAPPING.keys())

    if not access_token:
        access_token = os.getenv("META_ACCESS_TOKEN", "").strip() or None

    print("=" * 70)
    print("🚀 FAST META AD LIBRARY TO SHOPIFY LINK EXTRACTOR (LINKS ONLY)")
    print(f"[*] Target Country: {country}")
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

        print(f"\n📂 CATEGORY: {cat_name}")
        
        ads = []
        ads_per_kw = max(5, max_ads_per_keyword // len(keywords_list))

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
            print(f"   [{idx}/{len(ads)}] Checking: {dest_url}")

            # Lightweight Shopify verification check
            is_shopify, details = is_shopify_site(dest_url)
            if not is_shopify:
                continue

            lead = {
                "category_key": cat_key,
                "category_name": cat_name,
                "website_link": dest_url,
                "domain": domain
            }

            category_leads.append(lead)
            all_shopify_links.append(lead)
            print(f"      ✅ Valid Shopify Store: {domain}")

        # Save Category specific JSON
        json_file = os.path.join(output_dir, f"{cat_key}_links.json")
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(category_leads, f, indent=2, ensure_ascii=False)

        # Save Category specific Excel
        xlsx_file = os.path.join(output_dir, f"{cat_key}_links.xlsx")
        export_links_to_excel(category_leads, xlsx_file)

        print(f"📁 Category completed. Saved {len(category_leads)} Shopify store links.")

    # Save Master Consolidated JSON & Excel
    master_json = os.path.join(output_dir, "all_shopify_links.json")
    with open(master_json, "w", encoding="utf-8") as f:
        json.dump(all_shopify_links, f, indent=2, ensure_ascii=False)

    master_xlsx = os.path.join(output_dir, "all_shopify_links.xlsx")
    export_links_to_excel(all_shopify_links, master_xlsx)

    print("\n" + "=" * 70)
    print(f"✅ LINK EXTRACTION COMPLETED!")
    print(f"📄 Total Unique Shopify Store Links Extracted: {len(all_shopify_links)}")
    print(f"📁 Folder: {output_dir}")
    print("=" * 70)

    return all_shopify_links

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fast Meta Ad Library to Shopify Store Links Extractor")
    parser.add_argument("--categories", type=str, default=None, help="Comma-separated category keys")
    parser.add_argument("--country", type=str, default="PK", help="Target country code")
    parser.add_argument("--max_ads", type=int, default=100, help="Max ads per category")
    parser.add_argument("--token", type=str, default=None, help="Meta Graph API Token")

    args = parser.parse_args()
    
    selected_cats = None
    if args.categories:
        selected_cats = [c.strip() for c in args.categories.split(",") if c.strip()]

    run_link_extraction(selected_cats, country=args.country, max_ads_per_keyword=args.max_ads, access_token=args.token)
