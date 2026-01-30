from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import logging

from app.database import get_db_connection
from app.state_machine import ConversationStateMachine
from app.business_logic import save_entry, get_balances
from app.whatsapp import send_whatsapp_message

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Expense Tracker WhatsApp Bot")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/whatsapp")
async def whatsapp_webhook(request: Request):
    """
    Supports:
    - application/x-www-form-urlencoded (Twilio, curl -d)
    - application/json (Swagger tests)
    """

    content_type = request.headers.get("content-type", "")
    body_text = ""
    user_id = None

    # ---- Parse input safely ----
    try:
        if "application/json" in content_type:
            payload = await request.json()
            body_text = payload.get("Body", "") or payload.get("body", "")
            user_id = payload.get("From", "swagger-test")
        else:
            form = await request.form()
            body_text = form.get("Body", "")
            user_id = form.get("From", "")
    except Exception as e:
        logging.exception("Failed to parse request")
        return JSONResponse({"ok": False, "error": "Invalid request format"}, status_code=400)

    body_text = body_text.strip().lower()

    logging.info(f"Incoming message from {user_id}: {body_text}")

    if not body_text or not user_id:
        return {"ok": True}

    # ---- DB ----
    db = get_db_connection()
    cur = db.cursor(dictionary=True)

    # Ensure user exists
    cur.execute("INSERT IGNORE INTO users (user_id) VALUES (%s)", (user_id,))

    # Load conversation state
    cur.execute("SELECT * FROM conversation_state WHERE user_id=%s", (user_id,))
    state_row = cur.fetchone()

    fsm = ConversationStateMachine(cur, user_id, state_row)

    # ---- Simple NLP ----
    parsed = {
        "amount": None,
        "main_category": None,
        "sub_category": None,
        "date": None,
    }

    for token in body_text.split():
        if token.isdigit():
            parsed["amount"] = int(token)

        if token in ("needs", "wants", "savings"):
            parsed["main_category"] = {
                "needs": 1,
                "wants": 2,
                "savings": 3
            }[token]

        if token.isalpha() and token not in ("needs", "wants", "savings", "today", "yesterday"):
            parsed["sub_category"] = token.capitalize()

        if token in ("today", "yesterday") or "-" in token:
            parsed["date"] = token

    # ---- FSM ----
    response = fsm.handle_message(body_text, parsed)

    if response == "__SAVE_ENTRY__":
        amount, main_cat = save_entry(cur, user_id, fsm.state)

        balances = get_balances(cur, user_id)
        cur.execute("SELECT total_balance FROM users WHERE user_id=%s", (user_id,))
        total = cur.fetchone()["total_balance"]

        main_name = next(
            b["name"]
            for b in balances
            if b["id"] == main_cat
        )

        send_whatsapp_message(
            user_id,
            f"""✅ Expense saved
₹{amount}
Category: {main_name}
Total balance: ₹{int(total)}"""
        )
    else:
        send_whatsapp_message(user_id, response)

    db.commit()
    cur.close()
    db.close()

    return {"ok": True}
