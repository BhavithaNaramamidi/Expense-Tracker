from fastapi import FastAPI, Request
from app.database import get_db_connection
from app.state_machine import ConversationStateMachine
from app.business_logic import save_entry, get_balances
from app.whatsapp import send_whatsapp_message

app = FastAPI()

MAIN_CATEGORY_MAP = {
    "1": 1, "needs": 1,
    "2": 2, "wants": 2,
    "3": 3, "savings": 3
}

@app.post("/whatsapp")
async def whatsapp(request: Request):
    # ---- REQUIRED: needs python-multipart ----
    data = await request.form()

    msg_raw = data.get("Body", "")
    msg = msg_raw.strip().lower()
    user_id = data.get("From")

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

    # ---- PARSE MESSAGE SAFELY ----
    parsed = {
        "amount": None,
        "main_category": None,
        "sub_category": None
    }

    tokens = msg.split()

    for t in tokens:
        if t.isdigit():
            parsed["amount"] = int(t)

        if t in MAIN_CATEGORY_MAP:
            parsed["main_category"] = MAIN_CATEGORY_MAP[t]

        # sub-category must be STRING but stored as ID later by FSM
        if t.isalpha() and t not in MAIN_CATEGORY_MAP:
            parsed["sub_category"] = t.capitalize()

    # ---- FSM HANDLING ----
    response = fsm.handle_message(msg, parsed)

    # ---- SAVE FLOW ----
    if response == "__SAVE_ENTRY__":
        amount, main_cat_id = save_entry(cur, user_id, fsm.state)

        balances = get_balances(cur, user_id)
        cur.execute(
            "SELECT total_balance FROM users WHERE user_id=%s",
            (user_id,)
        )
        total = cur.fetchone()["total_balance"]

        main_name = next(
            b["name"] for b in balances if b["id"] == main_cat_id
        )

        send_whatsapp_message(
            user_id,
            f"✅ Saved\n₹{amount}\n{main_name} updated\nTotal balance: ₹{int(total)}"
        )
    else:
        send_whatsapp_message(user_id, response)

    db.commit()
    return {"ok": True}
