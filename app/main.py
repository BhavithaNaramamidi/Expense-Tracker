from fastapi import FastAPI, Request
from fastapi.responses import Response
from app.database import get_db_connection
from app.state_machine import ConversationStateMachine
from app.business_logic import save_entry, get_balances

app = FastAPI(title="Expense Tracker WhatsApp Bot")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/whatsapp")
async def whatsapp(request: Request):
    """
    Twilio WhatsApp Webhook
    MUST return TwiML (XML)
    """

    form = await request.form()
    msg = form.get("Body", "").strip().lower()
    user_id = form.get("From")

    db = get_db_connection()
    cur = db.cursor(dictionary=True)

    # ensure user exists
    cur.execute("INSERT IGNORE INTO users (user_id) VALUES (%s)", (user_id,))

    # fetch conversation state
    cur.execute(
        "SELECT * FROM conversation_state WHERE user_id=%s",
        (user_id,)
    )
    state_row = cur.fetchone()

    fsm = ConversationStateMachine(cur, user_id, state_row)

    # simple parser
    parsed = {
        "amount": None,
        "main_category": None,
        "sub_category": None
    }

    for t in msg.split():
        if t.isdigit():
            parsed["amount"] = int(t)

        if t in ["needs", "wants", "savings"]:
            parsed["main_category"] = {
                "needs": 1,
                "wants": 2,
                "savings": 3
            }[t]

        if t.isalpha() and t not in ["needs", "wants", "savings", "spent", "saved"]:
            parsed["sub_category"] = t.capitalize()

    response_text = fsm.handle_message(msg, parsed)

    if response_text == "__SAVE_ENTRY__":
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

        response_text = (
            f"✅ Saved\n"
            f"₹{amount}\n"
            f"{main_name} updated\n"
            f"Total balance: ₹{int(total)}"
        )

    db.commit()

    # 🔥 TWILIO EXPECTS XML (THIS IS THE KEY)
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>{response_text}</Message>
</Response>
"""

    return Response(content=twiml, media_type="application/xml")
