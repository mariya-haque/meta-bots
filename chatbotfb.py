"""
Facebook Page comment + Messenger auto-reply bot.

Two webhook surfaces on the same Page:
  - `feed`      new comments on posts -> public reply, plus a private reply that
                opens a Messenger thread with the commenter.
  - `messaging` Messenger DMs to the Page -> conversational reply.

Webhook fields to subscribe in the App dashboard: feed, messages,
messaging_postbacks. The Page token needs pages_messaging on top of
pages_manage_engagement.

Run:
    uvicorn chatbotfb:app --reload --port 8000
"""

import hashlib
import hmac
import logging
import os
from collections import OrderedDict

import httpx
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Request, Response
from openai import AsyncOpenAI

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("chatbotfb")

PAGE_ID = os.environ["FB_PAGE_ID"]
PAGE_ACCESS_TOKEN = os.environ["FB_PAGE_ACCESS_TOKEN"]
APP_SECRET = os.environ["FB_APP_SECRET"]
VERIFY_TOKEN = os.environ["FB_VERIFY_TOKEN"]
GRAPH_VERSION = os.getenv("FB_GRAPH_VERSION", "v23.0")
GRAPH_URL = f"https://graph.facebook.com/{GRAPH_VERSION}"

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-nano")
# Only reply to top-level comments by default. Replies-to-replies can spiral.
REPLY_TO_NESTED = os.getenv("REPLY_TO_NESTED", "false").lower() == "true"
# Dry run: generate the reply and log it, but don't post to Facebook.
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"
# Follow every public comment with a private reply, which opens a Messenger thread.
PRIVATE_REPLY = os.getenv("FB_PRIVATE_REPLY", "true").lower() == "true"
# Turns of DM history kept per user (one turn = user message + our reply).
DM_HISTORY_TURNS = int(os.getenv("FB_DM_HISTORY_TURNS", "8"))

# Deep link that drops someone straight into this Page's Messenger thread.
MESSENGER_LINK = f"https://m.me/{PAGE_ID}"

client = AsyncOpenAI()
app = FastAPI(title="FB Page Comment Bot")

SYSTEM_PROMPT = """You are the customer-support voice of our Facebook page, \
replying in public to a comment on one of our posts.

Rules:
- Keep it to 1-2 short sentences. This is a public comment thread, not an email.
- Warm and human. Match the commenter's language.
- Never invent prices, stock, delivery dates, policies, or order details. If the \
answer needs specifics you don't have, invite them to message the page instead: \
"Send us a DM and we'll sort it out!"
- If the comment is angry or a complaint, apologise once, don't get defensive, and \
move it to DMs.
- If the comment is spam, abusive, or not a real question, reply with exactly: SKIP
- No hashtags. No emoji spam (one is fine). Never mention being an AI."""

DM_SYSTEM_PROMPT = """You are the customer-support voice of our Facebook page, \
talking to someone one-on-one in Messenger.

Rules:
- This is a private chat, so you have more room than a public comment: 1-4 short \
sentences. Still conversational, not a formal email.
- Warm and human. Match the person's language.
- Never invent prices, stock, delivery dates, policies, or order details. If you \
don't know, say a human teammate will follow up here shortly.
- Ask one clarifying question when the request is vague, rather than guessing.
- If the message is abusive, reply with exactly: SKIP
- No hashtags. Never mention being an AI."""

PRIVATE_REPLY_TEMPLATE = os.getenv(
    "FB_PRIVATE_REPLY_TEXT",
    "Hi! We just replied to your comment — happy to help further right here in "
    "Messenger if you have any details to share. 🙂",
)


# Facebook retries deliveries, so the same comment can arrive more than once.
_seen: OrderedDict[str, None] = OrderedDict()
_SEEN_MAX = 5000

# Rolling DM transcript per sender id, so replies have conversational context.
# In-process only: restarting the app forgets every thread. Move to Redis before
# running more than one worker, or users will get half their history at random.
_dm_history: OrderedDict[str, list[dict]] = OrderedDict()
_DM_USERS_MAX = 1000


def already_handled(comment_id: str) -> bool:
    if comment_id in _seen:
        return True
    _seen[comment_id] = None
    if len(_seen) > _SEEN_MAX:
        _seen.popitem(last=False)
    return False


def remember(sender_id: str, role: str, content: str) -> None:
    turns = _dm_history.setdefault(sender_id, [])
    turns.append({"role": role, "content": content})
    del turns[: -DM_HISTORY_TURNS * 2]
    _dm_history.move_to_end(sender_id)
    if len(_dm_history) > _DM_USERS_MAX:
        _dm_history.popitem(last=False)


def valid_signature(body: bytes, header: str | None) -> bool:
    """Confirm the payload really came from Facebook."""
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.split("=", 1)[1])


@app.get("/webhook")
async def verify(request: Request):
    """One-time handshake when you subscribe the webhook in the App dashboard."""
    params = request.query_params
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == VERIFY_TOKEN:
        log.info("Webhook verified")
        return Response(content=params.get("hub.challenge", ""), media_type="text/plain")
    log.warning("Webhook verification failed")
    return Response(status_code=403)


@app.post("/webhook")
async def receive(request: Request, background: BackgroundTasks):
    body = await request.body()
    log.info("POST /webhook received (%d bytes)", len(body))

    if not valid_signature(body, request.headers.get("X-Hub-Signature-256")):
        log.warning("Rejected payload with bad signature")
        return Response(status_code=403)

    payload = await request.json()
    log.info("Webhook payload: object=%s", payload.get("object"))

    if payload.get("object") != "page":
        return {"status": "ignored"}

    for entry in payload.get("entry", []):
        changes = entry.get("changes", [])
        messaging = entry.get("messaging", [])
        log.info("Entry: %d changes, %d messaging events", len(changes), len(messaging))

        for change in changes:
            if change.get("field") == "feed":
                background.add_task(handle_feed_change, change.get("value", {}))

        # Messenger events hang off the entry itself, not off `changes`.
        for event in messaging:
            log.info("Messaging event from sender=%s", (event.get("sender") or {}).get("id"))
            background.add_task(handle_messaging_event, event)

    # Answer immediately — Facebook times out at 20s and re-delivers on failure.
    return {"status": "ok"}


async def handle_feed_change(value: dict) -> None:
    if value.get("item") != "comment" or value.get("verb") != "add":
        return

    comment_id = value.get("comment_id")
    message = (value.get("message") or "").strip()
    author_id = (value.get("from") or {}).get("id")
    post_id = value.get("post_id")
    parent_id = value.get("parent_id")

    if not comment_id or not message:
        return

    # Critical: never reply to ourselves, or the bot talks to itself forever.
    if author_id == PAGE_ID:
        return

    if already_handled(comment_id):
        log.info("Duplicate delivery for %s, skipping", comment_id)
        return

    # On a top-level comment, parent_id is the post. Anything else is a reply.
    if not REPLY_TO_NESTED and parent_id and parent_id != post_id:
        log.info("Skipping nested reply %s", comment_id)
        return

    try:
        reply = await compose_reply(message)
    except Exception:
        log.exception("OpenAI call failed for %s", comment_id)
        return

    if not reply or reply.strip().upper().startswith("SKIP"):
        log.info("Model declined to answer %s: %r", comment_id, message[:80])
        return

    if DRY_RUN:
        log.info("[DRY_RUN] would reply to %s: %s", comment_id, reply)
        return

    try:
        await post_reply(comment_id, reply)
        log.info("Replied to %s", comment_id)
    except Exception:
        log.exception("Failed to post reply to %s", comment_id)

    if PRIVATE_REPLY:
        try:
            await send_private_reply(comment_id, PRIVATE_REPLY_TEMPLATE)
            log.info("Opened Messenger thread from comment %s", comment_id)
        except Exception:
            # Expected to fail if the comment already got one, if it's older than
            # 7 days, or if the commenter blocks messages. Not worth an alert.
            log.warning("No private reply for %s", comment_id, exc_info=True)


async def handle_messaging_event(event: dict) -> None:
    sender_id = (event.get("sender") or {}).get("id")
    message = event.get("message") or {}

    # `is_echo` is our own outgoing message coming back to us. Replying to it
    # would put the bot in a loop with itself.
    if not sender_id or sender_id == PAGE_ID or message.get("is_echo"):
        return

    # Delivery receipts, read receipts and reactions all arrive here too.
    text = (message.get("text") or "").strip()
    if not text:
        return

    mid = message.get("mid")
    if mid and already_handled(mid):
        log.info("Duplicate delivery for %s, skipping", mid)
        return

    remember(sender_id, "user", text)

    try:
        reply = await compose_dm_reply(sender_id)
    except Exception:
        log.exception("OpenAI call failed for DM from %s", sender_id)
        return

    if not reply or reply.strip().upper().startswith("SKIP"):
        log.info("Model declined to answer DM from %s: %r", sender_id, text[:80])
        return

    remember(sender_id, "assistant", reply)

    if DRY_RUN:
        log.info("[DRY_RUN] would DM %s: %s", sender_id, reply)
        return

    try:
        await send_message(sender_id, reply)
        log.info("Replied to DM from %s", sender_id)
    except Exception:
        log.exception("Failed to send DM to %s", sender_id)


async def compose_reply(comment: str) -> str:
    response = await client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Comment on our post:\n\n{comment}"},
        ],
        max_tokens=150,
        temperature=0.7,
    )
    return (response.choices[0].message.content or "").strip()


async def compose_dm_reply(sender_id: str) -> str:
    response = await client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "system", "content": DM_SYSTEM_PROMPT}, *_dm_history[sender_id]],
        max_tokens=300,
        temperature=0.7,
    )
    return (response.choices[0].message.content or "").strip()


async def post_reply(comment_id: str, message: str) -> None:
    async with httpx.AsyncClient(timeout=15) as http:
        response = await http.post(
            f"{GRAPH_URL}/{comment_id}/comments",
            data={"message": message[:1000], "access_token": PAGE_ACCESS_TOKEN},
        )
        response.raise_for_status()


async def send_private_reply(comment_id: str, message: str) -> None:
    """Start a Messenger thread off the back of a public comment.

    Allowed once per comment, within 7 days of it being posted.
    """
    async with httpx.AsyncClient(timeout=15) as http:
        response = await http.post(
            f"{GRAPH_URL}/{comment_id}/private_replies",
            data={"message": message[:2000], "access_token": PAGE_ACCESS_TOKEN},
        )
        response.raise_for_status()


async def send_message(recipient_id: str, message: str) -> None:
    async with httpx.AsyncClient(timeout=15) as http:
        response = await http.post(
            f"{GRAPH_URL}/{PAGE_ID}/messages",
            params={"access_token": PAGE_ACCESS_TOKEN},
            json={
                "recipient": {"id": recipient_id},
                "message": {"text": message[:2000]},
                # RESPONSE keeps us inside the 24-hour standard messaging window.
                "messaging_type": "RESPONSE",
            },
        )
        response.raise_for_status()


@app.get("/")
async def root():
    return {
        "service": "Facebook Page comment + Messenger bot",
        "messenger": MESSENGER_LINK,
        "routes": {"webhook": "/webhook", "health": "/health", "docs": "/docs"},
    }


@app.get("/health")
async def health():
    return {
        "status": "up",
        "page_id": PAGE_ID,
        "messenger": MESSENGER_LINK,
        "model": OPENAI_MODEL,
        "dry_run": DRY_RUN,
        "private_reply": PRIVATE_REPLY,
        "active_dm_threads": len(_dm_history),
    }
