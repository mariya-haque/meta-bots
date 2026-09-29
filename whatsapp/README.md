# WhatsApp Cloud API Chatbot

A restaurant ordering bot for WhatsApp, built on Meta's **WhatsApp Cloud API** with a
FastAPI webhook, exposed to Meta through **ngrok**. Customers browse restaurants and
menus, build a cart and place an order inside WhatsApp; anything outside the ordering
flow gets an OpenAI-generated reply that remembers the last few turns of the
conversation.

```
WhatsApp user  ──▶  Meta Cloud API  ──▶  ngrok  ──▶  FastAPI (/webhook)  ──▶  OpenAI
      ▲                                                                          │
      └──────────────────  reply sent back via Cloud API  ◀─────────────────────┘
```

## Features

- **Restaurant picker** — interactive card for the demo restaurants (Hungry Habibi,
  Mandi House Sorriso, Toronto Gyros, Kababjees), then a photo catalog per restaurant.
- **Cart and checkout** — add items (including from native WhatsApp catalog `order`
  messages), switch restaurant (discards the cart), then step-by-step collection of
  name, phone and email.
- **Email confirmation** — an HTML order confirmation sent over SMTP (optional).
- **Meta catalog** — optional Commerce Manager catalog (`WA_CATALOG_ID`) for native
  product lists; `whatsapp_catalog.csv` is a sample product feed you can upload to it.
- **Dashboard** — `/dashboard` shows orders, lets you change order status, reply to a
  customer, and add/update/delete catalog products via the Graph API.
- **AI fallback** — OpenAI answers general questions in the customer's language.
- **Persistence** — orders and carts are saved to `orders.json` / `carts.json` next to
  the script (created at runtime, gitignored — they contain customer details).

## Prerequisites

- Python 3.10+
- A Meta developer app with the WhatsApp product, and an OpenAI API key
- [ngrok](https://ngrok.com/download) (or any public HTTPS URL) for the webhook
- *(Optional)* an SMTP account (e.g. a Gmail App Password) for confirmation emails

---

## 1. Install

```bash
cd Meta/whatsapp
python -m venv .venv
.venv\Scripts\activate        # Windows PowerShell
pip install -r requirements.txt
```

Copy the env template and fill it in (you'll get the WhatsApp values in step 3):

```bash
copy .env.example .env
```

---

## 2. Create the Meta app

1. Go to <https://developers.facebook.com/apps> → **Create app** → choose the
   **Business** type.
2. On the app dashboard, find **WhatsApp** and click **Set up**. This adds the
   WhatsApp product and gives you a free **test phone number** to send from.
3. Open **WhatsApp → API Setup**. Note these two values:
   - **Phone number ID**  → `WA_PHONE_NUMBER_ID`
   - **Temporary access token** (valid 24h) → `WA_ACCESS_TOKEN`
4. On that same page, under **Send and receive messages**, add *your own* phone
   number as a recipient (**To** field → Manage phone number list). WhatsApp only
   lets a test number message numbers you've verified.
5. Get your **App Secret**: **App settings → Basic → App Secret → Show**. Put it
   in `WA_APP_SECRET`.
6. Invent any string for `WA_VERIFY_TOKEN` (e.g. `my-verify-token-123`).

Also put your `OPENAI_API_KEY` in `.env`.

---

## 3. Run the server + ngrok

Terminal 1 — the bot:

```bash
uvicorn chatbot_whatsapp:app --reload --port 8000
# or: python chatbot_whatsapp.py   (port 8000, no reload)
```

Terminal 2 — the public tunnel:

```bash
ngrok http 8000
```

ngrok prints a public HTTPS URL like `https://abc123.ngrok-free.app`. Your webhook
URL is that plus `/webhook`:

```
https://abc123.ngrok-free.app/webhook
```

> Install ngrok from <https://ngrok.com/download> and run `ngrok config add-authtoken <token>` once (free account). The free URL changes every restart — you'll re-paste it in step 4 if you restart ngrok.

---

## 4. Connect the webhook to Meta

1. In the app dashboard: **WhatsApp → Configuration → Webhook → Edit**.
2. **Callback URL**: your ngrok URL + `/webhook`.
3. **Verify token**: the exact string you put in `WA_VERIFY_TOKEN`.
4. Click **Verify and save**. Meta sends a GET to `/webhook`; you should see
   `Webhook verified` in the uvicorn logs. (The server must be running first.)
5. Back on the Configuration page, under **Webhook fields**, click **Manage** and
   **Subscribe** to `messages`.

---

## 5. Test it

Send a WhatsApp message from the phone number you added in step 2.4 to the test
number. You should see the POST arrive in the logs and get an AI reply back.

Health check while it runs: <http://localhost:8000/health>
Order dashboard: <http://localhost:8000/dashboard>

Set `DRY_RUN=true` in `.env` to generate replies and log them without actually
sending — handy while wiring things up.

---

## Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `WA_PHONE_NUMBER_ID` | yes | | Phone number ID from API Setup |
| `WA_ACCESS_TOKEN` | yes | | Cloud API access token |
| `WA_APP_SECRET` | yes | | Verifies webhook signatures |
| `WA_VERIFY_TOKEN` | yes | | Any string; must match the webhook config |
| `OPENAI_API_KEY` | yes | | Read by the OpenAI SDK |
| `WA_DISPLAY_PHONE_NUMBER` | no | *(a hardcoded number)* | Business number used in the `wa.me/c/...` catalog link — set it to yours |
| `WA_CATALOG_ID` | no | *(blank)* | Commerce Manager catalog ID for native product lists and the dashboard catalog |
| `WA_GRAPH_VERSION` | no | `v25.0` | Graph API version |
| `WA_HISTORY_TURNS` | no | `8` | Conversation turns kept per user |
| `WA_MARK_READ` | no | `true` | Mark incoming messages as read |
| `DRY_RUN` | no | `false` | Log replies instead of sending them |
| `OPENAI_MODEL` | no | `gpt-5-nano` | Model for the AI fallback |
| `SMTP_SERVER` / `SMTP_PORT` | no | `smtp.gmail.com` / `587` | SMTP server for confirmation emails |
| `SMTP_EMAIL` / `SMTP_PASSWORD` | no | *(blank = emails skipped)* | SMTP login (use an App Password) |

---

## Going to production

The test setup is enough to demo. For real use:

- **Permanent token.** The 24h token expires. Create a **System User** in
  Meta Business Settings, assign it the app with `whatsapp_business_messaging`
  and `whatsapp_business_management`, and generate a non-expiring token → that
  becomes `WA_ACCESS_TOKEN`.
- **Real phone number.** Add and verify your own business number instead of the
  free test number, and complete business verification to lift messaging limits.
- **24-hour window.** You can only freely reply within 24h of the user's last
  message. To message someone outside that window you must use a pre-approved
  **message template**.
- **Persistence.** History and dedup are in-memory, and orders/carts live in local
  JSON files (see the comments in `chatbot_whatsapp.py`). Move them to Redis or a
  database before running more than one worker.
- **Protect the dashboard.** `/dashboard` and `/api/dashboard/*` have no
  authentication — put them behind auth or a private network before exposing the
  server publicly.
- **Stable URL.** Swap ngrok for a paid static domain or a real host so the
  webhook URL stops changing.

## Files

| File | What it is |
|------|-----------|
| `chatbot_whatsapp.py` | The FastAPI webhook, ordering flow, Cloud API sender and dashboard API |
| `templates/dashboard.html` | The order/catalog dashboard served at `/dashboard` |
| `whatsapp_catalog.csv` | Sample product feed for Meta Commerce Manager |
| `requirements.txt` | Python deps |
| `.env.example` | Copy to `.env` and fill in |
| `orders.json`, `carts.json` | Created at runtime; gitignored |
