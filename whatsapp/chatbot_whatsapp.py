"""
WhatsApp Restaurant Ordering Bot (WhatsApp Cloud API + OpenAI + SMTP Email).

Features:
  - Interactive Restaurant Card (Hungry Habibi, Mandi House Sorriso, Toronto Gyros, Kababjees)
  - Rich Photo Catalog with HD Food Pictures, Titles & Descriptions for every menu item
  - Smart Cart Management: "change restaurant" or selecting another restaurant discards previous cart
  - Step-by-step collection of Name, Phone Number, and Email Address
  - Automated HTML Email Confirmation via SMTP (App Password)
  - OpenAI Fallback for General Customer Assistance
"""

import hashlib
import hmac
import json
import logging
import os
import random
import smtplib
import time
from collections import OrderedDict
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Request, Response, Body
from fastapi.responses import HTMLResponse
from openai import AsyncOpenAI

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("chatbot_whatsapp")

# --- WhatsApp / Meta config -------------------------------------------------
PHONE_NUMBER_ID = os.environ["WA_PHONE_NUMBER_ID"]
ACCESS_TOKEN = os.environ["WA_ACCESS_TOKEN"]
APP_SECRET = os.environ["WA_APP_SECRET"]
VERIFY_TOKEN = os.environ["WA_VERIFY_TOKEN"]
CATALOG_ID = os.getenv("WA_CATALOG_ID", "")
GRAPH_VERSION = os.getenv("WA_GRAPH_VERSION", "v25.0")
GRAPH_URL = f"https://graph.facebook.com/{GRAPH_VERSION}"

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-nano")
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"
HISTORY_TURNS = int(os.getenv("WA_HISTORY_TURNS", "8"))
MARK_READ = os.getenv("WA_MARK_READ", "true").lower() == "true"

client = AsyncOpenAI()
app = FastAPI(title="WhatsApp Restaurant Ordering Bot")

SYSTEM_PROMPT = """You are a warm, helpful, and friendly customer-support assistant talking to someone on WhatsApp.
Rules:
- Keep replies short, warm, and conversational (1-3 sentences).
- If the user asks about menu, restaurants, or placing an order, guide them to type 'menu' or 'order'.
- Match the person's language (Roman Urdu, English, etc.).
- A single emoji is fine. Never mention being an AI."""

# WhatsApp duplicate delivery prevention
_seen: "OrderedDict[str, None]" = OrderedDict()
_SEEN_MAX = 5000

# OpenAI Chat history
_history: "OrderedDict[str, list[dict]]" = OrderedDict()
_USERS_MAX = 1000

# User Order Flow States & Persistence
_user_orders: dict[str, dict] = {}
_completed_orders: dict[str, dict] = {}

ORDERS_FILE = os.path.join(os.path.dirname(__file__), "orders.json")
CARTS_FILE = os.path.join(os.path.dirname(__file__), "carts.json")

def load_orders_from_file():
    global _completed_orders
    if os.path.exists(ORDERS_FILE):
        try:
            with open(ORDERS_FILE, "r", encoding="utf-8") as f:
                _completed_orders = json.load(f)
        except Exception as e:
            log.warning("Could not load orders.json: %s", e)

def save_orders_to_file():
    try:
        with open(ORDERS_FILE, "w", encoding="utf-8") as f:
            json.dump(_completed_orders, f, indent=2)
    except Exception as e:
        log.warning("Could not save orders.json: %s", e)

def load_carts_from_file():
    global _user_orders
    if os.path.exists(CARTS_FILE):
        try:
            with open(CARTS_FILE, "r", encoding="utf-8") as f:
                _user_orders = json.load(f)
        except Exception as e:
            log.warning("Could not load carts.json: %s", e)

def save_carts_to_file():
    try:
        with open(CARTS_FILE, "w", encoding="utf-8") as f:
            json.dump(_user_orders, f, indent=2)
    except Exception as e:
        log.warning("Could not save carts.json: %s", e)

# Load existing orders & carts on startup
load_orders_from_file()
load_carts_from_file()

# ----------------------------------------------------------------------------
# RESTAURANTS & RICH CATALOG DATA WITH HD PICTURES
# ----------------------------------------------------------------------------
RESTAURANTS = {
    "rest_1": {
        "name": "Hungry Habibi",
        "desc": "Middle Eastern & Fast Food",
        "menu": [
            {
                "id": "hh_1",
                "title": "Habibi Zinger Burger",
                "price": 650,
                "desc": "Crispy chicken zinger with spicy garlic sauce & melted cheese",
                "image": "https://images.unsplash.com/photo-1568901346375-23c9450c58cd?w=600",
            },
            {
                "id": "hh_2",
                "title": "Arabian Chicken Wrap",
                "price": 550,
                "desc": "Grilled chicken wrap with tahini & garlic sauce in warm pita",
                "image": "https://images.unsplash.com/photo-1626700051175-6818013e1d4f?w=600",
            },
            {
                "id": "hh_3",
                "title": "Loaded Beef Fries",
                "price": 700,
                "desc": "Golden crispy fries topped with spicy minced beef & cheddar",
                "image": "https://images.unsplash.com/photo-1585109649139-366815a0d713?w=600",
            },
            {
                "id": "hh_4",
                "title": "Habibi Special Platter",
                "price": 1200,
                "desc": "Mixed Arabic grill platter with fresh hummus & warm pita",
                "image": "https://images.unsplash.com/photo-1544025162-d76694265947?w=600",
            },
        ],
    },
    "rest_2": {
        "name": "Mandi House Sorriso",
        "desc": "Authentic Arabian Mandi & Rice",
        "menu": [
            {
                "id": "mhs_1",
                "title": "Chicken Mandi (Single)",
                "price": 1100,
                "desc": "Tender chicken cooked with authentic Yemeni spices & mandi rice",
                "image": "https://images.unsplash.com/photo-1633945274405-b6c8069047b0?w=600",
            },
            {
                "id": "mhs_2",
                "title": "Mutton Mandi Platter",
                "price": 2400,
                "desc": "Juicy slow-cooked mutton shank served with fragrant rice",
                "image": "https://images.unsplash.com/photo-1563379091339-03b21ab4a4f8?w=600",
            },
            {
                "id": "mhs_3",
                "title": "Kunafa Special",
                "price": 750,
                "desc": "Crispy golden Arabic dessert filled with sweet cream & pistachios",
                "image": "https://images.unsplash.com/photo-1579372786545-d24232daf58c?w=600",
            },
            {
                "id": "mhs_4",
                "title": "Arabic Mint Lemonade",
                "price": 350,
                "desc": "Refreshing chilled fresh mint lemonade drink",
                "image": "https://images.unsplash.com/photo-1513558161293-cdaf765ed2fd?w=600",
            },
        ],
    },
    "rest_3": {
        "name": "Toronto Gyros",
        "desc": "Greek & Mediterranean Street Food",
        "menu": [
            {
                "id": "tg_1",
                "title": "Original Beef Gyro",
                "price": 850,
                "desc": "Sliced beef gyro wrapped in warm pita with fresh tzatziki",
                "image": "https://images.unsplash.com/photo-1529006557810-274b9b2fc783?w=600",
            },
            {
                "id": "tg_2",
                "title": "Chicken Shawarma Plate",
                "price": 950,
                "desc": "Chicken shawarma served over rice with Greek salad & dip",
                "image": "https://images.unsplash.com/photo-1561758033-d89a9ad46330?w=600",
            },
            {
                "id": "tg_3",
                "title": "Falafel Pita Sandwich",
                "price": 600,
                "desc": "Crispy falafel balls in pita wrap with tahini sauce",
                "image": "https://images.unsplash.com/photo-1593001874117-c99c800e3eb7?w=600",
            },
            {
                "id": "tg_4",
                "title": "Greek Salad & Tzatziki",
                "price": 450,
                "desc": "Fresh cucumbers, kalamata olives, feta cheese & tzatziki dip",
                "image": "https://images.unsplash.com/photo-1540420773420-3366772f4999?w=600",
            },
        ],
    },
    "rest_4": {
        "name": "Kababjees",
        "desc": "Premium BBQ & Traditional Karahi",
        "menu": [
            {
                "id": "kbj_1",
                "title": "Chicken Reshmi Kabab",
                "price": 1150,
                "desc": "Melt-in-mouth chicken kababs grilled over charcoal",
                "image": "https://images.unsplash.com/photo-1599487488170-d11ec9c172f0?w=600",
            },
            {
                "id": "kbj_2",
                "title": "Mutton Karahi (Half)",
                "price": 1950,
                "desc": "Freshly cooked mutton karahi prepared in authentic desi ghee",
                "image": "https://images.unsplash.com/photo-1603894584373-5ac82b2ae398?w=600",
            },
            {
                "id": "kbj_3",
                "title": "Chicken Malai Boti",
                "price": 1250,
                "desc": "Creamy, tender grilled chicken boti served with mint chutney",
                "image": "https://images.unsplash.com/photo-1610057099443-fde8c4d50f91?w=600",
            },
            {
                "id": "kbj_4",
                "title": "Garlic Naan & Drink",
                "price": 250,
                "desc": "Freshly baked hot garlic naan + chilled beverage",
                "image": "https://images.unsplash.com/photo-1601050690597-df0568f70950?w=600",
            },
        ],
    },
}


def already_handled(message_id: str) -> bool:
    if message_id in _seen:
        return True
    _seen[message_id] = None
    if len(_seen) > _SEEN_MAX:
        _seen.popitem(last=False)
    return False


def remember(wa_id: str, role: str, content: str) -> None:
    turns = _history.setdefault(wa_id, [])
    turns.append({"role": role, "content": content})
    del turns[: -HISTORY_TURNS * 2]
    _history.move_to_end(wa_id)
    if len(_history) > _USERS_MAX:
        _history.popitem(last=False)


def valid_signature(body: bytes, header: "str | None") -> bool:
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.split("=", 1)[1])


# ----------------------------------------------------------------------------
# EMAIL CONFIRMATION VIA SMTP (DYNAMIC RUNTIME LOAD)
# ----------------------------------------------------------------------------
def send_email_confirmation(
    to_email: str, name: str, phone: str, restaurant: str, items: list, total_price: int, order_id: str
) -> None:
    load_dotenv(override=True)
    smtp_email = os.getenv("SMTP_EMAIL", "")
    smtp_password = os.getenv("SMTP_PASSWORD", "")
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))

    if not smtp_email or not smtp_password or smtp_email == "your-email@gmail.com":
        log.warning("SMTP credentials not configured in .env; skipping email notification.")
        return

    items_html = "".join(
        [
            f"<tr><td style='padding: 8px; border-bottom: 1px solid #eee;'>{i['title']}</td>"
            f"<td style='padding: 8px; border-bottom: 1px solid #eee; text-align: right;'>Rs. {i['price']}</td></tr>"
            for i in items
        ]
    )

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Order Confirmation #{order_id} - Food Express ({restaurant})"
        msg["From"] = f"Food Express <{smtp_email}>"
        msg["To"] = to_email

        html_content = f"""
        <html>
          <body style="font-family: Arial, sans-serif; color: #333; background-color: #f4f6f9; padding: 20px;">
            <div style="max-width: 550px; margin: 0 auto; background: #ffffff; border-radius: 12px; padding: 25px; box-shadow: 0 4px 10px rgba(0,0,0,0.08); border-top: 5px solid #e74c3c;">
              <h2 style="color: #e74c3c; text-align: center; margin-top: 0;">🎉 Order Confirmed!</h2>
              <p>Dear <strong>{name}</strong>,</p>
              <p>Thank you for ordering with <strong>Food Express</strong>! Your order summary is below:</p>
              <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
                <tr style="background-color: #f8f9fa;"><td style="padding: 10px; border-bottom: 1px solid #eee;"><strong>Order ID:</strong></td><td style="padding: 10px; border-bottom: 1px solid #eee; color: #e74c3c; text-align: right;">#{order_id}</td></tr>
                <tr><td style="padding: 10px; border-bottom: 1px solid #eee;"><strong>Restaurant:</strong></td><td style="padding: 10px; border-bottom: 1px solid #eee; text-align: right;">{restaurant}</td></tr>
              </table>
              <h4 style="color: #2c3e50; margin-bottom: 5px;">🛒 Items Ordered:</h4>
              <table style="width: 100%; border-collapse: collapse;">
                {items_html}
                <tr style="background-color: #e8f8f5;">
                  <td style="padding: 10px; font-weight: bold; color: #27ae60;">Total Bill Amount:</td>
                  <td style="padding: 10px; font-weight: bold; color: #27ae60; text-align: right; font-size: 16px;">Rs. {total_price}</td>
                </tr>
              </table>
              <h4 style="color: #2c3e50; margin-top: 20px; margin-bottom: 5px;">👤 Customer Details:</h4>
              <table style="width: 100%; border-collapse: collapse;">
                <tr><td style="padding: 6px; color: #555;">Name:</td><td style="padding: 6px; text-align: right;">{name}</td></tr>
                <tr><td style="padding: 6px; color: #555;">Phone:</td><td style="padding: 6px; text-align: right;">{phone}</td></tr>
                <tr><td style="padding: 6px; color: #555;">Email:</td><td style="padding: 6px; text-align: right;">{to_email}</td></tr>
              </table>
              <div style="background-color: #e8f8f5; border-left: 4px solid #2ecc71; padding: 12px; border-radius: 4px; font-size: 14px; margin-top: 20px;">
                🚴 Your delicious food is being prepared and will be delivered shortly!
              </div>
              <hr style="border: none; border-top: 1px solid #eee; margin: 25px 0 15px 0;" />
              <p style="text-align: center; color: #95a5a6; font-size: 12px;">Food Express • WhatsApp Ordering Service</p>
            </div>
          </body>
        </html>
        """
        msg.attach(MIMEText(html_content, "html"))

        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_email, smtp_password)
            server.sendmail(smtp_email, to_email, msg.as_string())

        log.info("Order confirmation email successfully sent to %s for Order #%s", to_email, order_id)
    except Exception:
        log.exception("Failed to send SMTP confirmation email to %s", to_email)


# ----------------------------------------------------------------------------
# FASTAPI WEBHOOK ENDPOINTS
# ----------------------------------------------------------------------------
@app.get("/webhook")
async def verify(request: Request):
    params = request.query_params
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == VERIFY_TOKEN:
        log.info("Webhook verified")
        return Response(content=params.get("hub.challenge", ""), media_type="text/plain")
    log.warning("Webhook verification failed")
    return Response(status_code=403)


@app.post("/webhook")
async def receive(request: Request, background: BackgroundTasks):
    body = await request.body()
    if not valid_signature(body, request.headers.get("X-Hub-Signature-256")):
        log.warning("Rejected payload with bad signature")
        return Response(status_code=403)

    payload = await request.json()
    if payload.get("object") != "whatsapp_business_account":
        return {"status": "ignored"}

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "messages":
                continue
            value = change.get("value", {})
            for message in value.get("messages", []):
                background.add_task(handle_message, message, value)

    return {"status": "ok"}


# ----------------------------------------------------------------------------
# MESSAGE HANDLING LOGIC & STATE MACHINE
# ----------------------------------------------------------------------------
async def handle_message(message: dict, value: dict) -> None:
    wa_id = message.get("from")
    message_id = message.get("id")
    msg_type = message.get("type")

    if not wa_id or not message_id:
        return

    if already_handled(message_id):
        log.info("Duplicate delivery for %s, skipping", message_id)
        return

    selected_id = ""
    text_content = ""

    if msg_type == "text":
        text_content = (message.get("text") or {}).get("body", "").strip()
    elif msg_type == "interactive":
        interactive = message.get("interactive") or {}
        list_reply = interactive.get("list_reply") or {}
        button_reply = interactive.get("button_reply") or {}
        selected_id = list_reply.get("id") or button_reply.get("id") or ""
        text_content = list_reply.get("title") or button_reply.get("title") or ""
    elif msg_type == "order":
        order_obj = message.get("order") or {}
        product_items = order_obj.get("product_items") or []

        contacts = value.get("contacts") or []
        contact_name = ""
        if contacts:
            contact_name = (contacts[0].get("profile") or {}).get("name", "")

        order_cart = []
        primary_restaurant_name = "Hungry Habibi"
        primary_restaurant_id = "rest_1"

        for p_item in product_items:
            p_id = p_item.get("product_retailer_id")
            qty = p_item.get("quantity", 1)
            for r_k, r_v in RESTAURANTS.items():
                for m_item in r_v["menu"]:
                    if m_item["id"] == p_id:
                        primary_restaurant_name = r_v["name"]
                        primary_restaurant_id = r_k
                        for _ in range(qty):
                            order_cart.append(m_item)
                        break

        if order_cart:
            import datetime
            now_str = datetime.datetime.now().strftime("%I:%M %p")
            _user_orders[wa_id] = {
                "step": "ENTER_PHONE" if contact_name else "ENTER_NAME",
                "name": contact_name,
                "phone": wa_id,
                "email": "",
                "restaurant_id": primary_restaurant_id,
                "restaurant_name": primary_restaurant_name,
                "cart": order_cart,
                "updated_at": now_str,
            }
            save_carts_to_file()

            items_str = "\n".join([f"• *{i['title']}* (Rs. {i['price']})" for i in order_cart])
            total = sum(i["price"] for i in order_cart)

            greeting = f"Thank you, *{contact_name}*! 👤\n\nNow please type your *Phone Number* for delivery contact:" if contact_name else "To complete your order, please type your *Full Name*:"

            msg = (
                f"🛍️ *WHATSAPP CATALOG ORDER RECEIVED!* 🎉\n\n"
                f"🏪 *Restaurant:* {primary_restaurant_name}\n\n"
                f"*Items in Cart:*\n{items_str}\n\n"
                f"💵 *Total Bill Amount:* *Rs. {total}*\n"
                f"-----------------------------------\n"
                f"{greeting}"
            )
            await send_text(wa_id, msg)
            return

    state = _user_orders.get(wa_id, {})
    step = state.get("step")
    lower_text = text_content.strip('"\' `').strip().lower()

    # Common greetings that should bypass name/phone checkout prompts
    chat_greetings = [
        "hi", "hello", "hey", "kese ho", "kaise ho", "kese hk", "kaise hk", "kya haal",
        "aoa", "assalam", "salaam", "reset", "start", "cancel"
    ]
    is_greeting = any(g == lower_text or g in lower_text for g in chat_greetings)

    # -------------------------------------------------------------------------
    # STAGE 1: Active Checkout Flow (ENTER_NAME, ENTER_PHONE, ENTER_EMAIL)
    # -------------------------------------------------------------------------
    if step == "ENTER_NAME" and text_content and not is_greeting and not any(k in lower_text for k in ["menu", "catalog", "order", "items"]):
        import datetime
        now_str = datetime.datetime.now().strftime("%I:%M %p")
        _user_orders[wa_id].update({
            "step": "ENTER_PHONE",
            "name": text_content,
            "updated_at": now_str,
        })
        save_carts_to_file()
        msg = f"Thank you, *{text_content}*! 👤\n\nNow please type your *Phone Number* for delivery contact:"
        await send_text(wa_id, msg)
        return

    if step == "ENTER_PHONE" and text_content and not is_greeting and not any(k in lower_text for k in ["menu", "catalog", "order", "items"]):
        import datetime
        now_str = datetime.datetime.now().strftime("%I:%M %p")
        _user_orders[wa_id].update({
            "step": "ENTER_EMAIL",
            "phone": text_content,
            "updated_at": now_str,
        })
        save_carts_to_file()
        msg = "Got it! 📱\n\nLastly, please enter your *Email Address* to receive your order confirmation email:"
        await send_text(wa_id, msg)
        return

    if step == "ENTER_EMAIL" and text_content and not is_greeting and not any(k in lower_text for k in ["menu", "catalog", "order", "items"]):
        email = text_content.strip()
        order_info = _user_orders[wa_id]
        order_id = str(random.randint(100000, 999999))

        name = order_info.get("name", "Valued Customer")
        phone = order_info.get("phone", wa_id)
        restaurant = order_info.get("restaurant_name", "Food Express")
        cart = order_info.get("cart", [])
        total_price = sum(i["price"] for i in cart) if cart else 0

        items_summary = "\n".join([f"• *{i['title']}* - Rs. {i['price']}" for i in cart])

        import datetime
        order_time = datetime.datetime.now().strftime("%I:%M %p, %d %b")

        _completed_orders[order_id] = {
            "order_id": order_id,
            "wa_id": wa_id,
            "name": name,
            "phone": phone,
            "email": email,
            "restaurant_name": restaurant,
            "items": cart,
            "total_price": total_price,
            "status": "Confirmed",
            "created_at": order_time,
        }
        save_orders_to_file()

        _user_orders.pop(wa_id, None)
        save_carts_to_file()

        send_email_confirmation(
            to_email=email,
            name=name,
            phone=phone,
            restaurant=restaurant,
            items=cart,
            total_price=total_price,
            order_id=order_id,
        )

        summary_msg = (
            f"✅ *ORDER CONFIRMED!* 🎉\n\n"
            f"🆔 *Order ID:* #{order_id}\n"
            f"🏪 *Restaurant:* {restaurant}\n\n"
            f"🛒 *Ordered Items:*\n{items_summary}\n\n"
            f"💵 *Total Bill:* *Rs. {total_price}*\n"
            f"-----------------------------------\n"
            f"👤 *Customer Name:* {name}\n"
            f"📞 *Phone:* {phone}\n"
            f"📧 *Email:* {email}\n\n"
            f"📧 *A confirmation email with your order summary has been sent to {email}!*\n\n"
            f"Thank you for ordering with Food Express! 😋\n\n"
            f"_Type *'order'* or *'menu'* anytime to place a new order._"
        )
        await send_text(wa_id, summary_msg)
        return

    # -------------------------------------------------------------------------
    # STAGE 2: Menu Item Selection & Add to Cart
    # -------------------------------------------------------------------------
    selected_item = None
    item_rest_name = None
    item_rest_key = None

    for r_key, r_val in RESTAURANTS.items():
        for menu_item in r_val["menu"]:
            if selected_id == menu_item["id"] or (text_content and menu_item["title"].lower() in lower_text):
                selected_item = menu_item
                item_rest_name = r_val["name"]
                item_rest_key = r_key
                break
        if selected_item:
            break

    if selected_item:
        cart = state.get("cart", [])
        cart.append(selected_item)
        import datetime
        now_str = datetime.datetime.now().strftime("%I:%M %p")
        _user_orders[wa_id] = {
            "step": "ENTER_NAME",
            "name": state.get("name", ""),
            "phone": state.get("phone", ""),
            "email": state.get("email", ""),
            "restaurant_id": item_rest_key,
            "restaurant_name": item_rest_name,
            "cart": cart,
            "updated_at": now_str,
        }
        save_carts_to_file()

        total = sum(i["price"] for i in cart)
        items_str = "\n".join([f"• *{i['title']}* (Rs. {i['price']})" for i in cart])

        msg = (
            f"🛒 *ITEM ADDED TO CART!*\n\n"
            f"🏪 *Restaurant:* {item_rest_name}\n\n"
            f"*Items in Cart:*\n{items_str}\n\n"
            f"💵 *Total Bill Amount:* *Rs. {total}*\n"
            f"-----------------------------------\n"
            f"👤 To complete your order, please type your *Full Name*:\n\n"
            f"_(Or type *'change restaurant'* to select another restaurant)_"
        )
        await send_text(wa_id, msg)
        return

    # -------------------------------------------------------------------------
    # STAGE 3: Specific Restaurant Matching
    # -------------------------------------------------------------------------
    matched_rest_key = None
    for r_k, r_v in RESTAURANTS.items():
        if selected_id == r_k or r_v["name"].lower() in lower_text:
            matched_rest_key = r_k
            break

    if not matched_rest_key:
        keywords = {
            "rest_1": ["habibi", "hungry habibi"],
            "rest_2": ["mandi house", "sorriso", "mandi"],
            "rest_3": ["toronto", "gyros"],
            "rest_4": ["kababjees", "kababjee"],
        }
        for r_k, kws in keywords.items():
            if any(kw in lower_text for kw in kws):
                matched_rest_key = r_k
                break

    if matched_rest_key:
        _user_orders[wa_id] = {
            "step": "SELECT_MENU",
            "restaurant_id": matched_rest_key,
            "restaurant_name": RESTAURANTS[matched_rest_key]["name"],
            "cart": [],
        }
        save_carts_to_file()
        await send_specific_restaurant_catalog(wa_id, matched_rest_key)
        return

    # -------------------------------------------------------------------------
    # STAGE 4: Unavailable Restaurant Detection
    # -------------------------------------------------------------------------
    unavailable_brands = ["kfc", "mcdonalds", "macdonalds", "mcdonald", "pizza hut", "dominos", "subway", "hardees", "broadway", "savour", "cheezious", "optp"]
    if any(b in lower_text for b in unavailable_brands):
        avail_list = "\n".join([f"{idx}. *{v['name']}* ({v['desc']})" for idx, v in enumerate(RESTAURANTS.values(), 1)])
        msg = (
            f"❌ *Restaurant Not Available!*\n\n"
            f"Sorry, the requested restaurant is currently not available in Food Express.\n\n"
            f"🏪 *Our Available Restaurants:* \n\n{avail_list}\n\n"
            f"Please type the name of any of the above restaurants to view its specific menu catalog!"
        )
        await send_text(wa_id, msg)
        return

    # -------------------------------------------------------------------------
    # STAGE 5: Explicit Full Menu / Catalog Request (Shows ALL items)
    # -------------------------------------------------------------------------
    menu_triggers = ["menu", "catalog", "order", "sections", "sets", "category", "categories", "all restaurants", "show menu", "menu dekhao", "menu dikhao", "list dekhao", "items", "sare items", "food list"]
    if any(t in lower_text for t in menu_triggers):
        if CATALOG_ID:
            await send_commerce_manager_product_list(wa_id)
        else:
            await send_multi_section_menu(wa_id)
        return

    # -------------------------------------------------------------------------
    # STAGE 6: Normal Conversational AI Reply (OpenAI Fallback)
    # -------------------------------------------------------------------------
    if text_content:
        remember(wa_id, "user", text_content)
        try:
            ai_reply = await compose_reply(wa_id)
            remember(wa_id, "assistant", ai_reply)
            await send_text(wa_id, ai_reply)
        except Exception as e:
            log.exception("OpenAI compose_reply failed: %s", e)
            await send_restaurant_card(wa_id)
        return

    _user_orders[wa_id] = {"step": "SELECT_RESTAURANT", "cart": []}
    await send_restaurant_card(wa_id)


async def send_specific_restaurant_catalog(wa_id: str, rest_key: str) -> None:
    """Send Native Meta Commerce Manager Catalog Product List for ONLY the specified restaurant."""
    rest = RESTAURANTS.get(rest_key, RESTAURANTS["rest_1"])

    if CATALOG_ID:
        product_items = [{"product_retailer_id": item["id"]} for item in rest["menu"]]
        sections = [{
            "title": rest["name"][:24],
            "product_items": product_items
        }]
        try:
            async with httpx.AsyncClient(timeout=15) as http:
                res = await http.post(
                    f"{GRAPH_URL}/{PHONE_NUMBER_ID}/messages",
                    headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
                    json={
                        "messaging_product": "whatsapp",
                        "recipient_type": "individual",
                        "to": wa_id,
                        "type": "interactive",
                        "interactive": {
                            "type": "product_list",
                            "header": {"type": "text", "text": f"🍽️ {rest['name']} Catalog"},
                            "body": {
                                "text": f"Explore our official menu catalog for *{rest['name']}* ({rest['desc']}):"
                            },
                            "footer": {"text": "Select an item to order"},
                            "action": {
                                "catalog_id": CATALOG_ID,
                                "sections": sections
                            },
                        },
                    },
                )
                res.raise_for_status()
                log.info("Specific catalog product_list sent successfully for %s to %s", rest_key, wa_id)
                return
        except Exception as e:
            log.exception("Failed to send specific restaurant product_list: %s", e)

    # Fallback to single-section interactive list message
    rows = []
    for item in rest["menu"]:
        rows.append({
            "id": item["id"],
            "title": item["title"][:24],
            "description": f"Rs. {item['price']} | {item['desc']}"[:72],
        })
    sections = [{"title": rest["name"][:24], "rows": rows}]

    try:
        async with httpx.AsyncClient(timeout=15) as http:
            res = await http.post(
                f"{GRAPH_URL}/{PHONE_NUMBER_ID}/messages",
                headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
                json={
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": wa_id,
                    "type": "interactive",
                    "interactive": {
                        "type": "list",
                        "header": {"type": "text", "text": f"🍽️ {rest['name']} Catalog"},
                        "body": {
                            "text": f"Explore the catalog menu items for *{rest['name']}* below:"
                        },
                        "footer": {"text": "Select an item to order"},
                        "action": {"button": "View Catalog 📜", "sections": sections},
                    },
                },
            )
            res.raise_for_status()
    except Exception as e:
        log.exception("Failed to send fallback catalog list: %s", e)
        msg = f"📜 *{rest['name']} Catalog Items:*\n\n"
        for idx, item in enumerate(rest["menu"], 1):
            msg += f"{idx}. *{item['title']}* - Rs. {item['price']}\n_{item['desc']}_\n\n"
        msg += "Type the item name to select!"
        await send_text(wa_id, msg)


async def send_native_catalog_message(wa_id: str) -> None:
    """Send Official Direct Catalog Link message with preview card (https://wa.me/c/923191976601)."""
    display_phone = os.getenv("WA_DISPLAY_PHONE_NUMBER", "923191976601")
    msg = (
        "🛍️ *Explore Our Official Food Catalog on WhatsApp!*\n\n"
        "Ordering is easy! Tap the link below to view items & purchase:\n\n"
        f"https://wa.me/c/{display_phone}\n\n"
        "Or type *'sections'* or *'menu'* to view our categorized restaurant sets!"
    )
    await send_text(wa_id, msg)


async def send_multi_section_menu(wa_id: str) -> None:
    """Send Interactive List Message with Multiple Sections (One section per Restaurant/Set)."""
    sections = []
    for k, v in RESTAURANTS.items():
        rows = []
        for item in v["menu"]:
            rows.append({
                "id": item["id"],
                "title": item["title"][:24],
                "description": f"Rs. {item['price']} | {item['desc']}"[:72],
            })
        sections.append({
            "title": v["name"][:24],
            "rows": rows[:10]  # Max 10 items total per list across sections
        })

    try:
        async with httpx.AsyncClient(timeout=15) as http:
            res = await http.post(
                f"{GRAPH_URL}/{PHONE_NUMBER_ID}/messages",
                headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
                json={
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": wa_id,
                    "type": "interactive",
                    "interactive": {
                        "type": "list",
                        "header": {"type": "text", "text": "🍔 Restaurant Menu Sets"},
                        "body": {
                            "text": "Browse food items organized by Restaurant Sets & Categories below:"
                        },
                        "footer": {"text": "Select an item to add to your order"},
                        "action": {"button": "View Restaurant Sets 🍽️", "sections": sections},
                    },
                },
            )
            res.raise_for_status()
    except Exception as e:
        log.exception("Failed to send multi-section list: %s", e)
        await send_restaurant_card(wa_id)


async def send_commerce_manager_product_list(wa_id: str) -> None:
    """Send Native Meta Commerce Manager Product List Message using CATALOG_ID and Sets."""
    if not CATALOG_ID:
        log.warning("WA_CATALOG_ID is not set in .env. Falling back to multi-section list.")
        await send_multi_section_menu(wa_id)
        return

    sections = []
    for k, v in RESTAURANTS.items():
        product_items = [{"product_retailer_id": item["id"]} for item in v["menu"]]
        sections.append({
            "title": v["name"][:24],
            "product_items": product_items
        })

    try:
        async with httpx.AsyncClient(timeout=15) as http:
            res = await http.post(
                f"{GRAPH_URL}/{PHONE_NUMBER_ID}/messages",
                headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
                json={
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": wa_id,
                    "type": "interactive",
                    "interactive": {
                        "type": "product_list",
                        "header": {"type": "text", "text": "🍽️ Food Express Menu Sets"},
                        "body": {
                            "text": "Explore our restaurant sets from Meta Commerce Manager:"
                        },
                        "footer": {"text": "Select an item to order"},
                        "action": {
                            "catalog_id": CATALOG_ID,
                            "sections": sections
                        },
                    },
                },
            )
            if res.is_error:
                log.error("Meta Graph API error on product_list: Status %s - %s", res.status_code, res.text)
                res.raise_for_status()
            log.info("Meta product_list sent successfully to %s", wa_id)
    except Exception as e:
        log.exception("Failed to send Meta Commerce Manager product_list message: %s. Falling back to multi-section menu.", e)
        await send_multi_section_menu(wa_id)



async def send_restaurant_card(wa_id: str) -> None:
    rows = []
    for k, v in RESTAURANTS.items():
        rows.append({"id": k, "title": v["name"][:24], "description": v["desc"][:72]})

    sections = [{"title": "Select Restaurant"[:24], "rows": rows}]

    try:
        async with httpx.AsyncClient(timeout=15) as http:
            res = await http.post(
                f"{GRAPH_URL}/{PHONE_NUMBER_ID}/messages",
                headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
                json={
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": wa_id,
                    "type": "interactive",
                    "interactive": {
                        "type": "list",
                        "header": {"type": "text", "text": "🍔 Food Express Ordering"},
                        "body": {
                            "text": "Welcome! Please tap the button below and select your favorite restaurant from the list:"
                        },
                        "footer": {"text": "Select 1 of 4 Restaurants"},
                        "action": {"button": "View Restaurants 🍽️", "sections": sections},
                    },
                },
            )
            res.raise_for_status()
    except Exception as e:
        log.exception("Failed to send interactive restaurant card: %s", e)
        msg = "🍔 *Food Express Restaurants:*\n\n"
        for idx, (k, v) in enumerate(RESTAURANTS.items(), 1):
            msg += f"{idx}. *{v['name']}* - {v['desc']}\n"
        msg += "\nType the restaurant name to view its catalog menu!"
        await send_text(wa_id, msg)


async def send_visual_catalog(wa_id: str, rest_key: str) -> None:
    """Send HD Food Pictures + Descriptions for every catalog item, followed by Interactive Item Selector Card."""
    rest = RESTAURANTS.get(rest_key, RESTAURANTS["rest_1"])

    # 1. Send Intro Header
    await send_text(wa_id, f"📜 *{rest['name'].upper()} CATALOG & MENU*\n_{rest['desc']}_")

    # 2. Send Photo Cards for each item in catalog
    for item in rest["menu"]:
        caption = f"🖼️ *{item['title']}*\n📝 {item['desc']}\n💰 *Price:* Rs. {item['price']}"
        try:
            await send_image_message(wa_id, item["image"], caption)
        except Exception:
            log.warning("Could not send image for %s, sending text caption", item["title"])
            await send_text(wa_id, caption)

    # 3. Send Interactive List Card to select item
    rows = []
    for item in rest["menu"]:
        rows.append({
            "id": item["id"],
            "title": item["title"][:24],
            "description": f"Rs. {item['price']} | {item['desc']}"[:72],
        })

    sec_title = f"{rest['name']} Menu"[:24]
    sections = [{"title": sec_title, "rows": rows}]

    try:
        async with httpx.AsyncClient(timeout=15) as http:
            res = await http.post(
                f"{GRAPH_URL}/{PHONE_NUMBER_ID}/messages",
                headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
                json={
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": wa_id,
                    "type": "interactive",
                    "interactive": {
                        "type": "list",
                        "header": {"type": "text", "text": f"🍲 Select Meal"},
                        "body": {
                            "text": "Tap the button below to select an item from the catalog to add to your order:"
                        },
                        "footer": {"text": "Tap button to add item to cart"},
                        "action": {"button": "Add to Cart 🛒", "sections": sections},
                    },
                },
            )
            res.raise_for_status()
    except Exception as e:
        log.exception("Failed to send interactive catalog menu card: %s", e)
        msg = f"📜 *{rest['name']} Menu Items:*\n\n"
        for idx, item in enumerate(rest["menu"], 1):
            msg += f"{idx}. *{item['title']}* - Rs. {item['price']}\n_{item['desc']}_\n\n"
        msg += "Type the item name to select!"
        await send_text(wa_id, msg)


async def send_image_message(wa_id: str, image_url: str, caption: str) -> None:
    async with httpx.AsyncClient(timeout=15) as http:
        response = await http.post(
            f"{GRAPH_URL}/{PHONE_NUMBER_ID}/messages",
            headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
            json={
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": wa_id,
                "type": "image",
                "image": {"link": image_url, "caption": caption[:1024]},
            },
        )
        response.raise_for_status()


async def compose_reply(wa_id: str) -> str:
    params = {
        "model": OPENAI_MODEL,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, *_history.get(wa_id, [])],
    }
    if any(m in OPENAI_MODEL.lower() for m in ["gpt-5", "o1", "o3"]):
        params["max_completion_tokens"] = 2000
    else:
        params["max_tokens"] = 300
        params["temperature"] = 0.7
    response = await client.chat.completions.create(**params)
    return (response.choices[0].message.content or "").strip()


async def send_text(wa_id: str, text: str) -> None:
    async with httpx.AsyncClient(timeout=15) as http:
        response = await http.post(
            f"{GRAPH_URL}/{PHONE_NUMBER_ID}/messages",
            headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
            json={
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": wa_id,
                "type": "text",
                "text": {"preview_url": True, "body": text[:4096]},
            },
        )
        response.raise_for_status()


async def mark_read(message_id: str) -> None:
    async with httpx.AsyncClient(timeout=15) as http:
        response = await http.post(
            f"{GRAPH_URL}/{PHONE_NUMBER_ID}/messages",
            headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
            json={
                "messaging_product": "whatsapp",
                "status": "read",
                "message_id": message_id,
            },
        )
        response.raise_for_status()


@app.get("/")
async def root():
    return {
        "service": "WhatsApp Restaurant Photo Catalog Bot",
        "restaurants": [r["name"] for r in RESTAURANTS.values()],
        "routes": {"dashboard": "/dashboard", "webhook": "/webhook", "health": "/health", "docs": "/docs"},
    }


@app.get("/health")
async def health():
    return {"status": "ok", "orders_count": len(_completed_orders), "active_carts": len(_user_orders)}


# ----------------------------------------------------------------------------
# ADMIN DASHBOARD API & ENDPOINTS
# ----------------------------------------------------------------------------


@app.get("/dashboard", response_class=HTMLResponse)
async def serve_dashboard():
    dashboard_path = os.path.join(os.path.dirname(__file__), "templates", "dashboard.html")
    if os.path.exists(dashboard_path):
        with open(dashboard_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h2>Dashboard Template Not Found</h2>", status_code=404)


@app.get("/api/dashboard/data")
async def get_dashboard_data():
    load_orders_from_file()
    load_carts_from_file()
    active_carts = []
    for wa_id, state in _user_orders.items():
        if state.get("cart"):
            rest_key = state.get("restaurant_id", "")
            rest_name = RESTAURANTS.get(rest_key, {}).get("name", "Restaurant") if rest_key else state.get("restaurant_name", "Browsing...")
            active_carts.append({
                "wa_id": wa_id,
                "name": state.get("name", "Customer Browsing"),
                "phone": state.get("phone", wa_id),
                "email": state.get("email", ""),
                "restaurant_name": rest_name,
                "cart": state.get("cart", []),
                "step": state.get("step", ""),
                "updated_at": state.get("updated_at", "Just now"),
            })

    orders_list = list(_completed_orders.values())
    orders_list.reverse()  # Newest first

    total_revenue = sum(o.get("total_price", 0) for o in _completed_orders.values())
    out_for_delivery_count = sum(1 for o in _completed_orders.values() if o.get("status") == "Out for Delivery")
    delivered_count = sum(1 for o in _completed_orders.values() if o.get("status") == "Delivered")

    return {
        "active_carts": active_carts,
        "orders": orders_list,
        "stats": {
            "total_revenue": total_revenue,
            "active_carts_count": len(active_carts),
            "out_for_delivery_count": out_for_delivery_count,
            "delivered_count": delivered_count,
            "total_orders": len(_completed_orders),
        }
    }


@app.post("/api/dashboard/orders/{order_id}/status")
async def update_order_status(order_id: str, payload: dict = Body(...)):
    order = _completed_orders.get(order_id)
    if not order:
        return Response(status_code=404, content="Order not found")

    new_status = payload.get("status", "Confirmed")
    order["status"] = new_status
    save_orders_to_file()
    wa_id = order.get("wa_id")
    name = order.get("name", "Customer")
    restaurant = order.get("restaurant_name", "Food Express")

    if payload.get("send_whatsapp_alert", True) and wa_id:
        try:
            if new_status == "Out for Delivery":
                msg = (
                    f"🛵 *ORDER UPDATE: OUT FOR DELIVERY!* 🚴\n\n"
                    f"Dear *{name}*,\n"
                    f"Your order *#{order_id}* from *{restaurant}* has been picked up by our rider and is now *OUT FOR DELIVERY*!\n\n"
                    f"🚴 Our delivery rider is on the way to your address with your hot food! Please stay available."
                )
                await send_text(wa_id, msg)
            elif new_status == "Delivered":
                msg = (
                    f"✅ *ORDER DELIVERED!* 🎉\n\n"
                    f"Dear *{name}*,\n"
                    f"Your order *#{order_id}* from *{restaurant}* has been successfully delivered!\n\n"
                    f"Thank you for choosing Food Express! Enjoy your meal 😋"
                )
                await send_text(wa_id, msg)
            elif new_status == "Preparing":
                msg = (
                    f"👨‍🍳 *KITCHEN UPDATE!*\n\n"
                    f"Dear *{name}*,\n"
                    f"Your order *#{order_id}* from *{restaurant}* is currently being prepared by our chef!"
                )
                await send_text(wa_id, msg)
        except Exception as e:
            log.warning("Could not send WhatsApp status notification for order #%s: %s", order_id, e)

    return {"status": "ok", "order_id": order_id, "new_status": new_status}


@app.post("/api/dashboard/send-reply")
async def send_dashboard_reply(payload: dict = Body(...)):
    wa_id = payload.get("wa_id")
    message = payload.get("message", "").strip()

    if not wa_id or not message:
        return Response(status_code=400, content="wa_id and message are required")

    try:
        await send_text(wa_id, message)
    except Exception as e:
        log.exception("Failed to send custom reply to %s: %s", wa_id, e)
        return Response(status_code=500, content=f"Failed to send WhatsApp message: {str(e)}")

    return {"status": "ok", "wa_id": wa_id}


async def sync_local_restaurants_with_meta():
    """Fetch all products from Meta Catalog API and sync with local RESTAURANTS dict."""
    if not CATALOG_ID:
        return
    url = f"{GRAPH_URL}/{CATALOG_ID}/products?fields=id,retailer_id,name,description,price,currency,image_url,availability,brand&limit=100"
    try:
        async with httpx.AsyncClient(timeout=15) as http:
            res = await http.get(url, headers={"Authorization": f"Bearer {ACCESS_TOKEN}"})
            if res.status_code == 200:
                meta_products = res.json().get("data", [])
                
                # Re-build local menus from live Meta catalog data
                for r_v in RESTAURANTS.values():
                    r_v["menu"] = []

                for p in meta_products:
                    brand_name = p.get("brand", "").strip().lower()
                    ret_id = p.get("retailer_id") or p.get("id")
                    title = p.get("name", "Food Item")
                    desc = p.get("description", "")
                    raw_price = p.get("price", "PKR 0")
                    try:
                        num_price = int(float(raw_price.replace("PKR", "").replace(",", "").strip()))
                    except Exception:
                        num_price = 500
                    image = p.get("image_url", "")
                    avail = p.get("availability", "in stock")

                    if avail != "in stock":
                        continue

                    item_dict = {
                        "id": ret_id,
                        "title": title,
                        "price": num_price,
                        "desc": desc,
                        "image": image,
                    }

                    matched = False
                    for r_v in RESTAURANTS.values():
                        if r_v["name"].lower() == brand_name or r_v["name"].lower() in brand_name:
                            r_v["menu"].append(item_dict)
                            matched = True
                            break
                    if not matched:
                        RESTAURANTS["rest_1"]["menu"].append(item_dict)
    except Exception as e:
        log.warning("Could not sync local RESTAURANTS with Meta: %s", e)


# ----------------------------------------------------------------------------
# META CATALOG MANAGEMENT API ENDPOINTS
# ----------------------------------------------------------------------------
@app.get("/api/dashboard/catalog")
async def get_catalog_products():
    if not CATALOG_ID:
        return {"error": "WA_CATALOG_ID is not configured", "products": []}

    url = f"{GRAPH_URL}/{CATALOG_ID}/products?fields=id,retailer_id,name,description,price,currency,image_url,availability,brand&limit=100"
    try:
        async with httpx.AsyncClient(timeout=15) as http:
            res = await http.get(url, headers={"Authorization": f"Bearer {ACCESS_TOKEN}"})
            if res.status_code == 200:
                data = res.json().get("data", [])
                await sync_local_restaurants_with_meta()
                return {"status": "ok", "catalog_id": CATALOG_ID, "count": len(data), "products": data}
            return {"error": f"Meta Graph API error {res.status_code}", "details": res.json(), "products": []}
    except Exception as e:
        log.exception("Error fetching Meta catalog products: %s", e)
        return {"error": str(e), "products": []}


@app.post("/api/dashboard/catalog/add")
async def add_catalog_product(payload: dict = Body(...)):
    if not CATALOG_ID:
        return Response(status_code=400, content="CATALOG_ID not set")

    retailer_id = payload.get("retailer_id") or f"custom_{int(time.time())}"
    name = payload.get("name", "").strip()
    description = payload.get("description", "").strip()
    price_val = float(payload.get("price", 0))
    price_cents = str(int(price_val * 100))
    currency = payload.get("currency", "PKR")
    image_url = payload.get("image_url", "https://images.unsplash.com/photo-1568901346375-23c9450c58cd?w=600").strip()
    brand = payload.get("brand", "Hungry Habibi").strip()
    availability = payload.get("availability", "in stock")

    url = f"{GRAPH_URL}/{CATALOG_ID}/products"
    data = {
        "retailer_id": retailer_id,
        "name": name,
        "description": description,
        "price": price_cents,
        "currency": currency,
        "image_url": image_url,
        "availability": availability,
        "brand": brand,
        "category": "Food & Beverages"
    }

    try:
        async with httpx.AsyncClient(timeout=15) as http:
            res = await http.post(url, headers={"Authorization": f"Bearer {ACCESS_TOKEN}"}, data=data)
            if res.status_code in [200, 201]:
                res_data = res.json()
                await sync_local_restaurants_with_meta()
                return {"status": "ok", "meta_product_id": res_data.get("id"), "retailer_id": retailer_id}
            return Response(status_code=res.status_code, content=json.dumps(res.json()))
    except Exception as e:
        log.exception("Error adding product to Meta catalog: %s", e)
        return Response(status_code=500, content=str(e))


@app.post("/api/dashboard/catalog/{product_id}/update")
async def update_catalog_product(product_id: str, payload: dict = Body(...)):
    url = f"{GRAPH_URL}/{product_id}"
    data = {}
    if "name" in payload:
        data["name"] = payload["name"]
    if "description" in payload:
        data["description"] = payload["description"]
    if "price" in payload:
        data["price"] = str(int(float(payload["price"]) * 100))
        data["currency"] = "PKR"
    if "availability" in payload:
        data["availability"] = payload["availability"]
    if "image_url" in payload:
        data["image_url"] = payload["image_url"]
    if "brand" in payload:
        data["brand"] = payload["brand"]

    try:
        async with httpx.AsyncClient(timeout=15) as http:
            res = await http.post(url, headers={"Authorization": f"Bearer {ACCESS_TOKEN}"}, data=data)
            if res.status_code == 200:
                await sync_local_restaurants_with_meta()
                return {"status": "ok", "product_id": product_id, "updated_fields": list(data.keys())}
            return Response(status_code=res.status_code, content=json.dumps(res.json()))
    except Exception as e:
        log.exception("Error updating Meta catalog product %s: %s", product_id, e)
        return Response(status_code=500, content=str(e))


@app.delete("/api/dashboard/catalog/{product_id}")
async def delete_catalog_product(product_id: str):
    url = f"{GRAPH_URL}/{product_id}"
    try:
        async with httpx.AsyncClient(timeout=15) as http:
            res = await http.delete(url, headers={"Authorization": f"Bearer {ACCESS_TOKEN}"})
            if res.status_code == 200:
                await sync_local_restaurants_with_meta()
                return {"status": "ok", "deleted_id": product_id}
            return Response(status_code=res.status_code, content=json.dumps(res.json()))
    except Exception as e:
        log.exception("Error deleting Meta catalog product %s: %s", product_id, e)
        return Response(status_code=500, content=str(e))



@app.get("/health")
async def health():
    return {
        "status": "up",
        "phone_number_id": PHONE_NUMBER_ID,
        "model": OPENAI_MODEL,
        "active_orders": len(_user_orders),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
