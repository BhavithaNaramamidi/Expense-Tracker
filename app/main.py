from fastapi import FastAPI, Form
from app.database import get_db_connection
from app.state_machine import ConversationStateMachine
from app.business_logic import save_entry, get_balances
from app.whatsapp import send_whatsapp_message

app = FastAPI()

@app.post("/whatsapp")
async def whatsapp(
    Body: str = Form(...),
    From: str = Form(...)
):
    # Normalize input
    msg = Body.strip().lower()
    user_id = From.strip()

    db = get_db_connection()
    cur = db.cursor(dictionary=True)

    # Ensure user exists
    cur.execute(
        "INSERT IGNORE INTO users (user_id) VALUES (%s)",
        (user_id,)
    )

    # Fetch conversation state
    cur.execute(
        "SELECT * FROM conversation_state WHERE user_id=%s",
        (user_id,)
    )
    state_row = cur.fetchone()

    # Initialize FSM
    fsm = ConversationStateMachine(cur, user_id, state_row)

    # -------- PARSING LOGIC (UNCHANGED) --------
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

        if (
            t.isalpha()
            and t not in ["needs", "wants", "savings", "spent", "saved"]
        ):
            parsed["sub_category"] = t.capitalize()

    # -------- FSM HANDLING --------
    response = fsm.handle_message(msg, parsed)

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
            if b["name"].lower().startswith(
                "n" if main_cat == 1 else
                "w" if main_cat == 2 else
                "s"
            )
        )

        send_whatsapp_message(
            user_id,
            f"✅ Saved\n₹{amount}\n{main_name} updated\nTotal balance: ₹{int(total)}"
        )
    else:
        send_whatsapp_message(user_id, response)

    db.commit()
    return {"ok": True}
