from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from app.database import get_db_connection
from app.state_machine import ConversationStateMachine
from app.business_logic import save_entry, get_balances
from app.whatsapp import send_whatsapp_message

app = FastAPI(title="Expense Tracker WhatsApp Bot")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/whatsapp")
async def whatsapp_webhook(request: Request):
    # 🔑 Handle BOTH Twilio (form) and Swagger/curl (json)
    content_type = request.headers.get("content-type", "")

    if "application/json" in content_type:
        payload = await request.json()
        msg = payload.get("Body", "").strip().lower()
        user_id = payload.get("From", "swagger-test")
    else:
        form = await request.form()
        msg = form.get("Body", "").strip().lower()
        user_id = form.get("From")

    if not msg or not user_id:
        return PlainTextResponse("ok")

    db = get_db_connection()
    cur = db.cursor(dictionary=True)

    # Ensure user exists
    cur.execute(
        "INSERT IGNORE INTO users (user_id, total_balance) VALUES (%s, 0)",
        (user_id,)
    )

    # Fetch conversation state
    cur.execute(
        "SELECT * FROM conversation_state WHERE user_id=%s",
        (user_id,)
    )
    state_row = cur.fetchone()

    fsm = ConversationStateMachine(cur, user_id, state_row)

    # Simple parser (FSM does the real work)
    parsed = {
        "amount": None,
        "main_category": None,
        "sub_category": None
    }

    for token in msg.split():
        if token.isdigit():
            parsed["amount"] = int(token)
        elif token in ["needs", "wants", "savings"]:
            parsed["main_category"] = {
                "needs": 1,
                "wants": 2,
                "savings": 3
            }[token]
        elif token.isalpha() and token not in ["spent", "saved"]:
            parsed["sub_category"] = token.capitalize()

    response = fsm.handle_message(msg, parsed)

    if response == "__SAVE_ENTRY__":
        amount, main_cat = save_entry(cur, user_id, fsm.state)

        balances = get_balances(cur, user_id)
        cur.execute(
            "SELECT total_balance FROM users WHERE user_id=%s",
            (user_id,)
        )
        total = cur.fetchone()["total_balance"]

        main_name = (
            "Needs" if main_cat == 1
            else "Wants" if main_cat == 2
            else "Savings"
        )

        send_whatsapp_message(
            user_id,
            f"✅ Saved\n₹{amount}\n{main_name} updated\nTotal balance: ₹{int(total)}"
        )
    else:
        send_whatsapp_message(user_id, response)

    db.commit()
    cur.close()
    db.close()

    # Twilio only needs 200 OK
    return PlainTextResponse("ok")
