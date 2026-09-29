import os
import zipfile

def create_leads_zip():
    leads_dir = "leads"
    zip_filename = os.path.join(leads_dir, "shopify_excel_leads.zip")
    
    if not os.path.exists(leads_dir):
        print(f"[!] '{leads_dir}' directory does not exist.")
        return

    excel_files = [f for f in os.listdir(leads_dir) if f.endswith(".xlsx") and not f.startswith("~$")]
    
    if not excel_files:
        print("[!] No Excel (.xlsx) files found to zip.")
        return

    print(f"[*] Creating ZIP archive containing {len(excel_files)} Excel files...")
    
    with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for file in excel_files:
            file_path = os.path.join(leads_dir, file)
            zipf.write(file_path, arcname=file)
            print(f"   [+] Added: {file}")

    print(f"[+] Successfully created ZIP archive: {os.path.abspath(zip_filename)}")

if __name__ == "__main__":
    create_leads_zip()
