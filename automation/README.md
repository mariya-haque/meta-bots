# 🚀 Meta Ad Library to Shopify Lead Extractor

An automated Python script that searches the Meta (Facebook) Ad Library for a set of predefined product categories (e.g. `makeup`, `footwear`, `womens_clothing_abaya`), extracts ad destination websites, checks if the target site is built on **Shopify**, and automatically scrapes public contact info (Store Name, Emails, Phone numbers, and Instagram profile), saving everything as JSON and Excel files in a `leads/` folder.

Phone extraction is tuned for **Pakistan** (`03xx…`, `+92…` and major landline codes), and the default Ad Library country is `PK`.

> ⚠️ **Use responsibly.** The output contains third-party business contact details. Scraped lead files are gitignored and must not be committed or redistributed. Respect Meta's and each website's terms of service and applicable anti-spam / data-protection laws when using the results.

---

## 🛠️ Requirements

### 1. Software Prerequisites:
* **Python 3.8+** installed on your system.
* **Pip** (Python package installer).

### 2. Required Python Libraries:
* `playwright`: For stealth browser control & rendering dynamic Meta Ad Library pages.
* `httpx`: For fast HTTP requests & checking endpoints.
* `beautifulsoup4` & `lxml`: For HTML parsing and link discovery.
* `pandas` & `openpyxl`: For writing the Excel (`.xlsx`) lead files.
* `python-dotenv`: For loading settings from `.env`.

---

## 💻 Quick Setup Instructions

### Step 1: Install Dependencies
Open your terminal / Command Prompt in this folder (`Meta/automation`) and run:

```bash
pip install -r requirements.txt
playwright install chromium
```

### Step 2: Configure (optional)
```bash
cp .env.example .env      # Windows: copy .env.example .env
```

| Variable | Default | Purpose |
|---|---|---|
| `META_ACCESS_TOKEN` | *(blank)* | Meta Graph API token. If set, the official Ad Library API is tried first; otherwise Playwright browser scraping is used |
| `DEFAULT_COUNTRY` | `PK` | Default for `--country` |
| `MAX_ADS_PER_KEYWORD` | `50` | Default for `--max_ads` |
| `HEADLESS_MODE` | `true` | Set to `false` to watch the browser open and scroll while scraping |
| `PROXY_URL` | *(blank)* | Optional proxy for the Playwright browser (if scraping heavily) |

---

## ⚡ How to Run the Automation

Always run the scripts from this folder — output goes to `./leads/`.

### Default Run (all categories):
```bash
python main.py
```

### Selected Categories, Country & Limit:
```bash
python main.py --categories "makeup,footwear,watches" --country "PK" --max_ads 15
```

Available category keys: `womens_clothing_abaya`, `mens_clothing_kurta`, `beauty_skincare_makeup`, `makeup`, `skincare`, `jewelry_artificial`, `bags_purses`, `footwear`, `mobile_accessories`, `home_decor`, `baby_kids`, `health_wellness`, `perfumes_attars`, `bedsheets_linen`, `watches`, `fitness_gym`. Each maps to a few search keywords in `CATEGORIES_MAPPING` in `main.py`.

### Using Meta API (Optional, if you have a Meta Graph Token):
```bash
python main.py --categories "makeup" --token "YOUR_META_ACCESS_TOKEN"
```

### Post-processing helpers:
```bash
python verify_leads_shopify.py   # re-checks every leads/*.xlsx with the strict Shopify detector and rewrites it (+ matching .json)
python zip_leads.py              # bundles leads/*.xlsx into leads/shopify_excel_leads.zip
```

---

## 📂 Output Data Format

Everything is written to the `leads/` folder (created automatically, gitignored):

| File | Contents |
|---|---|
| `leads/<category>_leads.json` | Leads for one category |
| `leads/<category>_leads.xlsx` | Same, as a spreadsheet (Category, Store Name, Website Link, Emails, Phones, Instagram) |
| `leads/all_shopify_leads.json` / `.xlsx` | All categories combined, de-duplicated by domain |
| `leads/shopify_excel_leads.zip` | Created by `zip_leads.py` |

Example JSON record:

```json
[
  {
    "category_key": "makeup",
    "category_name": "Makeup",
    "website_name": "Glow Cosmetics",
    "website_link": "https://glowcosmeticsexample.com",
    "is_shopify": true,
    "contact_info": {
      "emails": [
        "support@glowcosmeticsexample.com"
      ],
      "phones": [
        "+923001234567"
      ],
      "instagram": "https://www.instagram.com/glowcosmetics"
    },
    "scraped_pages": [
      "https://glowcosmeticsexample.com",
      "https://glowcosmeticsexample.com/pages/contact"
    ]
  }
]
```

---

## 🔍 How Each Module Works

1. **`meta_ad_scraper.py`**:
   Opens Meta Ad Library using Playwright stealth browser, searches for keywords, scrolls through ads, and extracts external store destination links. Also contains the optional Graph API fetcher.

2. **`shopify_detector.py`**:
   Checks target websites for Shopify signatures without needing browser extensions:
   - Scans HTML for `cdn.shopify.com`, `window.Shopify`, and `<meta generator="Shopify">`.
   - Probes the `/cart.json` endpoint and validates the JSON response.

3. **`contact_scraper.py`**:
   Crawls the store homepage plus up to three contact / about pages linked from it to extract:
   - Store Name from OpenGraph / Page Title / Shopify script variables.
   - Clean Emails & Phone numbers via Regex.
   - Instagram handle / profile link.

4. **`main.py`**: Runs the pipeline per category and writes the JSON/Excel files.

5. **`verify_leads_shopify.py`** / **`zip_leads.py`**: Post-processing helpers (see above).

---

## 🧪 Selenium Variant (`selenium_shopify_meta_scraper/`)

An alternative implementation of the same pipeline using **Selenium + Chrome** (via `webdriver-manager`) instead of Playwright, with `phonenumbers`-based Pakistani phone validation. It has its own `requirements.txt` and `.env.example` (`META_ACCESS_TOKEN`, `HEADLESS_MODE`) and writes inside its own folder:

```bash
cd selenium_shopify_meta_scraper
pip install -r requirements.txt           # needs Google Chrome installed
cp .env.example .env

python main.py --categories "watches,footwear" --country PK --max_ads 15
#   -> selenium_shopify_meta_scraper/leads/<category>_leads.json / .xlsx, all_shopify_leads.*

python fast_shopify_link_extractor.py --max_ads 100
#   -> selenium_shopify_meta_scraper/leads_links_only/<category>_links.json / .xlsx
#      (Shopify store links only, no contact scraping)
```

---

## 📁 Project Structure

```
automation/
├── main.py                    # Playwright pipeline entry point
├── meta_ad_scraper.py         # Ad Library scraping (browser + Graph API)
├── shopify_detector.py        # Shopify detection
├── contact_scraper.py         # Store name / email / phone / Instagram extraction
├── verify_leads_shopify.py    # Strict re-verification of leads/*.xlsx
├── zip_leads.py               # Zips leads/*.xlsx
├── requirements.txt
├── .env.example
├── leads/                     # generated output (gitignored)
└── selenium_shopify_meta_scraper/   # Selenium variant (own requirements/.env)
```
