# Facebook Page Comment Bot

Auto-replies to comments on your Facebook Page's posts using OpenAI, and
answers Messenger DMs to the Page.

> This folder also contains two separate projects, each with its own README:
> [`automation/`](automation/) (Meta Ad Library to Shopify lead scraper) and
> [`whatsapp/`](whatsapp/) (WhatsApp Cloud API ordering bot).

## How it works

1. Someone comments on one of your Page posts.
2. Facebook POSTs a `feed` webhook event to `/webhook`.
3. The signature is verified, the comment is deduped and filtered.
4. OpenAI drafts a short reply.
5. The reply is posted back via `POST /{comment-id}/comments`.
6. Unless `FB_PRIVATE_REPLY=false`, a private reply is also sent
   (`POST /{comment-id}/private_replies`), opening a Messenger thread.

Messenger DMs to the Page arrive as `messaging` events on the same `/webhook`
and get a conversational reply, with the last few turns of history kept in
memory per user.

## Prerequisites

- Python 3.10+
- A Facebook Page, and a Meta developer app you can add webhooks to
- An OpenAI API key
- A public HTTPS URL for the webhook (e.g. ngrok for local testing)

## Project structure

```
Meta/
├── chatbotfb.py       # FastAPI app: /webhook (GET verify, POST events), /, /health
├── requirements.txt
├── .env.example
├── automation/        # separate project: Meta Ad Library -> Shopify lead scraper
└── whatsapp/          # separate project: WhatsApp Cloud API bot
```

## Setup

### 1. Install and configure

```bash
pip install -r requirements.txt
cp .env.example .env   # then fill it in
```

### 2. Facebook App

At [developers.facebook.com](https://developers.facebook.com) create an app of
type **Business** and add the **Webhooks** and **Facebook Login for Business**
products.

Generate a **Page Access Token** for your Page with these permissions:

- `pages_manage_engagement` — post the replies
- `pages_read_engagement` — read the comments
- `pages_messaging` — send private replies and answer Messenger DMs

Short-lived tokens expire in ~1 hour. Exchange yours for a long-lived one:

```bash
curl -G "https://graph.facebook.com/v23.0/oauth/access_token" \
  -d grant_type=fb_exchange_token \
  -d client_id=YOUR_APP_ID \
  -d client_secret=YOUR_APP_SECRET \
  -d fb_exchange_token=SHORT_LIVED_TOKEN
```

### 3. Expose the server

Facebook needs a public HTTPS URL. For local testing:

```bash
uvicorn chatbotfb:app --reload --port 8000
ngrok http 8000
```

### 4. Subscribe the webhook

In **App Dashboard > Webhooks > Page**:

- Callback URL: `https://your-ngrok-url/webhook`
- Verify Token: the same `FB_VERIFY_TOKEN` from your `.env`
- Subscribe to the **`feed`**, **`messages`** and **`messaging_postbacks`** fields

Then subscribe your Page to the app:

```bash
curl -X POST "https://graph.facebook.com/v23.0/YOUR_PAGE_ID/subscribed_apps" \
  -d subscribed_fields=feed,messages,messaging_postbacks \
  -d access_token=YOUR_PAGE_ACCESS_TOKEN
```

## Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `FB_PAGE_ID` | yes | | Your Page's numeric ID |
| `FB_PAGE_ACCESS_TOKEN` | yes | | Page token (see permissions above) |
| `FB_APP_SECRET` | yes | | Verifies `X-Hub-Signature-256` on webhooks |
| `FB_VERIFY_TOKEN` | yes | | Any string; must match the webhook setup form |
| `OPENAI_API_KEY` | yes | | Read by the OpenAI SDK |
| `FB_GRAPH_VERSION` | no | `v23.0` | Graph API version |
| `OPENAI_MODEL` | no | `gpt-5-nano` | Model used for replies |
| `REPLY_TO_NESTED` | no | `false` | Also reply to replies-to-comments |
| `DRY_RUN` | no | `false` | Log replies instead of posting them |
| `FB_PRIVATE_REPLY` | no | `true` | Send a Messenger private reply after each public reply |
| `FB_PRIVATE_REPLY_TEXT` | no | built-in greeting | Text of that private reply |
| `FB_DM_HISTORY_TURNS` | no | `8` | DM turns kept per user for context |

## Before you go live

`DRY_RUN=true` is set in `.env.example` (the code itself defaults to `false`). Leave it on for the first
round of testing — the bot logs the reply it *would* post without publishing
anything. Comment on your own post from a second account, read the logs, and
only flip it to `false` once the replies look right.

**Tune the tone first.** `SYSTEM_PROMPT` (comments) and `DM_SYSTEM_PROMPT`
(Messenger) in [chatbotfb.py](chatbotfb.py) are generic. Edit it to describe your actual business, products, and hours before
it starts talking to customers in public.

## Guardrails already in place

- **Signature verification** — payloads without a valid `X-Hub-Signature-256`
  are rejected, so nobody can forge comment events.
- **Self-reply loop prevention** — comments authored by the Page itself are
  ignored. Without this the bot replies to its own replies forever.
- **Deduplication** — Facebook retries deliveries; each `comment_id` is only
  handled once (in-memory, so it resets on restart).
- **Top-level only** — nested replies are skipped by default
  (`REPLY_TO_NESTED=false`) to avoid long back-and-forth threads.
- **SKIP escape hatch** — the model answers `SKIP` for spam or abuse, and
  nothing is posted.

## Known limits

- DM history is in-memory too, so a restart forgets every conversation.
- Dedupe is in-memory. Running more than one worker, or restarting mid-retry,
  can produce a double reply. Move `_seen` to Redis if you scale out.
- `verb == "add"` only, so edited comments don't trigger a new reply.
- No rate limiting. A viral post means one OpenAI call per comment.
- Nothing here reviews replies before they go public. Public replies are hard
  to walk back — watch the logs for the first few days.
