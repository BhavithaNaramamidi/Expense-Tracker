from fastapi import FastAPI, Form
from app.database import get_db_connection
from app.state_machine import ConversationStateMachine
from app.business_logic import save_entry, get_balances
from app.whatsapp import send_whatsapp_message

app = FastAPI()

# Fixed mapping (IDs only)
MAIN_CATEGORY_MAP = {
    "needs": 1,
    "wants": 2,
    "savings": 3
}

@app.post("/whatsapp")
async def whatsapp(
    Body: str = Form(...),
    From: str = Form(...)
):
    # ----------------------------
    # Normalize input
    # ----------------------------
    raw_message = Body.strip()
    msg = raw_message.lower()
    user_id = From.strip()

    # ----------------------------
    # DB connection
    # ----------------------------
    db = get_db_connection()
    cur = db.cursor(dictionary=True)

    # ----------------------------
    # Ensure user exists
    # ----------------------------
    cur.execute(
        "INSERT IGNORE INTO users (user_id, total_balance) VALUES (%s, 0)",
        (user_id,)
    )

    # ----------------------------
    # Load conversation state
    # ----------------------------
    cur.execute(
        "SELECT * FROM conversation_state WHERE user_id=%s",
        (user_id,)
    )
    state_row = cur.fetchone()

    fsm = ConversationStateMachine(cur, user_id, state_row)

    # ----------------------------
    # Parse user message (NO DB writes here)
    # ----------------------------
    parsed = {
        "amount": None,
        "main_category_id": None,
        "sub_category_name": None
    }

    for token in msg.split():
        # Amount
        if token.isdigit():
            parsed["amount"] = int(token)

        # Main category
        if token in MAIN_CATEGORY_MAP:
            parsed["main_category_id"] = MAIN_CATEGORY_MAP[token]

        # Sub-category name (text only)
        if (
            token.isalpha()
            and token not in ["needs", "wants", "savings", "spent", "saved"]
        ):
            parsed["sub_category_name"] = token.capitalize()

    # ----------------------------
    # FSM handling
    # ----------------------------
    response = fsm.handle_message(parsed)

    # ----------------------------
    # Save entry
    # ----------------------------
    if response == "__SAVE_ENTRY__":
        amount, main_cat_id = save_entry(cur, user_id, fsm.state)

        # Fetch total balance
        cur.execute(
            "SELECT total_balance FROM users WHERE user_id=%s",
            (user_id,)
        )
        total_balance = cur.fetchone()["total_balance"]

        main_name = {
            1: "Needs",
            2: "Wants",
            3: "Savings"
        }[main_cat_id]

        send_whatsapp_message(
            user_id,
            f"✅ Saved\n"
            f"₹{amount}\n"
            f"{main_name} updated\n"
            f"Total balance: ₹{int(total_balance)}"
        )
    else:
        # FSM prompt / response
        send_whatsapp_message(user_id, response)

    db.commit()
    return {"ok": True}
