from fastapi import FastAPI, Request
from app.database import get_db_connection
from app.state_machine import ConversationStateMachine
from app.business_logic import save_entry, get_balances
from app.whatsapp import send_whatsapp_message

app = FastAPI(
    title="Expense Tracker WhatsApp Bot",
    version="0.1.0"
)

# --------------------------------------------------
# Health check (VERY important for Railway)
# --------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok"}

# --------------------------------------------------
# WhatsApp Webhook (Twilio + Swagger + cURL safe)
# --------------------------------------------------
@app.post("/whatsapp")
async def whatsapp(request: Request):
    """
    Handles WhatsApp webhook calls.
    Supports:
    - application/x-www-form-urlencoded (Twilio)
    - application/json (Swagger / tests)
    """

    content_type = request.headers.get("content-type", "")

    msg = ""
    user_id = ""

    # ---------- 1. Read input safely ----------
    if "application/json" in content_type:
        body = await request.json()
        msg = str(body.get("Body", "")).strip()
        user_id = body.get("From", "swagger-user")

    else:
        form = await request.form()
        msg = str(form.get("Body", "")).strip()
        user_id = form.get("From", "whatsapp-user")

    if not msg:
        return {"ok": True}

    msg_lower = msg.lower()

    # ---------- 2. DB setup ----------
    db = get_db_connection()
    cur = db.cursor(dictionary=True)

    cur.execute(
        "INSERT IGNORE INTO users (user_id) VALUES (%s)",
        (user_id,)
    )

    cur.execute(
        "SELECT * FROM conversation_state WHERE user_id=%s",
        (user_id,)
    )
    state_row = cur.fetchone()

    fsm = ConversationStateMachine(cur, user_id, state_row)

    # ---------- 3. Parse message ----------
    parsed = {
        "amount": None,
        "main_category": None,
        "sub_category": None
    }

    for token in msg_lower.split():
        if token.isdigit():
            parsed["amount"] = int(token)

        if token in ("needs", "wants", "savings"):
            parsed["main_category"] = {
                "needs": 1,
                "wants": 2,
                "savings": 3
            }[token]

        if token.isalpha() and token not in (
            "needs", "wants", "savings",
            "spent", "saved", "today", "yesterday"
        ):
            parsed["sub_category"] = token.capitalize()

    # ---------- 4. FSM ----------
    response = fsm.handle_message(msg_lower, parsed)

    # ---------- 5. Save if needed ----------
    if response == "__SAVE_ENTRY__":
        amount, main_cat = save_entry(cur, user_id, fsm.state)

        balances = get_balances(cur, user_id)

        cur.execute(
            "SELECT total_balance FROM users WHERE user_id=%s",
            (user_id,)
        )
        total = cur.fetchone()["total_balance"]

        main_name = next(
            b["name"]
            for b in balances
            if b["id"] == main_cat
        )

        send_whatsapp_message(
            user_id,
            f"✅ Saved\n₹{amount}\n{main_name} updated\nTotal balance: ₹{int(total)}"
        )

    else:
        send_whatsapp_message(user_id, response)

    db.commit()
    return {"ok": True}
