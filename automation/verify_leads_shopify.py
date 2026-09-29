import os
import json
import pandas as pd
from urllib.parse import urlparse
from shopify_detector import is_shopify_site

def verify_all_excel_files():
    leads_dir = "leads"
    
    if not os.path.exists(leads_dir):
        print(f"[!] '{leads_dir}' directory does not exist.")
        return

    # Find all category excel files
    files = [f for f in os.listdir(leads_dir) if f.endswith(".xlsx") and not f.startswith("~$") and not f.startswith("strictly_verified")]

    if not files:
        print("[!] No Excel files found to verify.")
        return

    print("=" * 70)
    print(f"[*] Starting strict Shopify verification audit on {len(files)} Excel files...")
    print("=" * 70)

    for file in files:
        filepath = os.path.join(leads_dir, file)
        print(f"\n[Processing File]: {file}")
        
        try:
            df = pd.read_excel(filepath)
        except Exception as e:
            print(f"   [!] Failed to read {file}: {e}")
            continue

        if df.empty:
            print("   [!] File is empty. Skipping.")
            continue

        verified_leads = []
        skipped_count = 0
        total_rows = len(df)

        for idx, row in df.iterrows():
            url = row.get("Website Link")
            store_name = row.get("Store Name")
            category = row.get("Category")
            
            if not url or not isinstance(url, str):
                continue

            parsed = urlparse(url)
            domain = parsed.netloc.lower()

            # Filter out known non-Shopify marketplaces/app stores
            is_marketplace = any(m in domain for m in [
                "amazon.com", "play.google.com", "itunes.apple.com", "shein.com", "meesho", "facebook.com", "instagram.com", "tiktok.com"
            ])

            if is_marketplace:
                print(f"      [{idx+1}/{total_rows}] [-] Removed Platform/Marketplace: {domain}")
                skipped_count += 1
                continue

            # Run backend check
            is_shopify, details = is_shopify_site(url)
            if is_shopify:
                print(f"      [{idx+1}/{total_rows}] [+] VERIFIED SHOPIFY: {domain}")
                verified_leads.append({
                    "Category": category if category else file.replace("_leads.xlsx", "").replace("_", " ").title(),
                    "Store Name": store_name,
                    "Website Link": url,
                    "Emails": row.get("Emails"),
                    "Phones": row.get("Phones"),
                    "Instagram": row.get("Instagram")
                })
            else:
                print(f"      [{idx+1}/{total_rows}] [-] Failed Shopify Backend Check: {domain}")
                skipped_count += 1

        # Overwrite the Excel and JSON file with strictly verified Shopify leads
        verified_df = pd.DataFrame(verified_leads)
        
        # Overwrite Excel sheet
        try:
            verified_df.to_excel(filepath, index=False)
            print(f"   [Excel Saved]: {filepath} ({len(verified_leads)} Verified, {skipped_count} Skipped)")
        except PermissionError:
            fallback = filepath.replace(".xlsx", "_verified_copy.xlsx")
            verified_df.to_excel(fallback, index=False)
            print(f"   [!] File was locked. Saved verified copy to: {fallback}")

        # Overwrite JSON sheet
        json_filepath = os.path.join(leads_dir, file.replace(".xlsx", ".json"))
        try:
            with open(json_filepath, "w", encoding="utf-8") as f:
                json.dump(verified_leads, f, indent=2, ensure_ascii=False)
            print(f"   [JSON Saved]: {json_filepath}")
        except Exception as e:
            print(f"   [!] Failed to write JSON: {e}")

    print("\n" + "=" * 70)
    print("ALL EXCEL FILES AUDITED AND FILTERED SUCCESSFULLY!")
    print("=" * 70)

if __name__ == "__main__":
    verify_all_excel_files()
