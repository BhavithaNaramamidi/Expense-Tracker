from fastapi import FastAPI, Request
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
    form = await request.form()

    body = (form.get("Body") or "").strip().lower()
    user_id = form.get("From")

    if not user_id:
        return {"ok": True}

    db = get_db_connection()
    cur = db.cursor(dictionary=True)

    # Ensure user exists
    cur.execute(
        "INSERT IGNORE INTO users (user_id, total_balance) VALUES (%s, 0)",
        (user_id,)
    )

    # Load conversation state
    cur.execute(
        "SELECT * FROM conversation_state WHERE user_id=%s",
        (user_id,)
    )
    state_row = cur.fetchone()

    fsm = ConversationStateMachine(cur, user_id, state_row)

    # Parse message
    parsed = {
        "amount": None,
        "main_category": None,
        "sub_category": None
    }

    for token in body.split():
        if token.isdigit():
            parsed["amount"] = int(token)

        if token in ("needs", "wants", "savings"):
            parsed["main_category"] = {
                "needs": 1,
                "wants": 2,
                "savings": 3
            }[token]

        if token.isalpha() and token not in ("needs", "wants", "savings", "spent", "saved"):
            parsed["sub_category"] = token.capitalize()

    response = fsm.handle_message(body, parsed)

    if response == "__SAVE_ENTRY__":
        amount, main_cat = save_entry(cur, user_id, fsm.state)

        balances = get_balances(cur, user_id)
        cur.execute(
            "SELECT total_balance FROM users WHERE user_id=%s",
            (user_id,)
        )
        total = cur.fetchone()["total_balance"]

        main_name = next(
            b["name"] for b in balances
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
