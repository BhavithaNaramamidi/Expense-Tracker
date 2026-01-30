from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.database import get_db_connection
from app.state_machine import ConversationStateMachine
from app.business_logic import save_entry, get_balances
from app.whatsapp import send_whatsapp_message

app = FastAPI(title="Expense Tracker WhatsApp Bot")


# ------------------------
# Health check (Railway)
# ------------------------
@app.get("/health")
def health():
    return {"status": "ok"}


# ------------------------
# WhatsApp Webhook
# ------------------------
@app.post("/whatsapp")
async def whatsapp(request: Request):
    """
    Supports:
    - application/x-www-form-urlencoded (Twilio)
    - application/json (Swagger / curl tests)
    """

    try:
        # ------------------------
        # Read incoming payload
        # ------------------------
        content_type = request.headers.get("content-type", "")

        if "application/json" in content_type:
            payload = await request.json()
            msg = str(payload.get("Body", "")).strip()
            user_id = payload.get("From", "test-user")
        else:
            form = await request.form()
            msg = str(form.get("Body", "")).strip()
            user_id = form.get("From", "test-user")

        if not msg:
            send_whatsapp_message(user_id, "Please send a message")
            return JSONResponse({"ok": True})

        msg_lower = msg.lower()

        # ------------------------
        # DB setup
        # ------------------------
        db = get_db_connection()
        cur = db.cursor(dictionary=True)

        # Ensure user exists
        cur.execute(
            "INSERT IGNORE INTO users (user_id) VALUES (%s)",
            (user_id,)
        )

        # Load conversation state
        cur.execute(
            "SELECT * FROM conversation_state WHERE user_id=%s",
            (user_id,)
        )
        state_row = cur.fetchone()

        fsm = ConversationStateMachine(cur, user_id, state_row)

        # ------------------------
        # Parse message (basic NLP)
        # ------------------------
        parsed = {
            "amount": None,
            "main_category": None,
            "sub_category": None,
        }

        tokens = msg_lower.split()

        for t in tokens:
            if t.isdigit():
                parsed["amount"] = int(t)

            if t in ("needs", "wants", "savings"):
                parsed["main_category"] = {
                    "needs": 1,
                    "wants": 2,
                    "savings": 3,
                }[t]

            if t.isalpha() and t not in (
                "needs", "wants", "savings", "spent", "saved"
            ):
                parsed["sub_category"] = t.capitalize()

        # ------------------------
        # FSM handling
        # ------------------------
        response = fsm.handle_message(msg_lower, parsed)

        # ------------------------
        # Save entry
        # ------------------------
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
                if (
                    (main_cat == 1 and b["name"].lower().startswith("n")) or
                    (main_cat == 2 and b["name"].lower().startswith("w")) or
                    (main_cat == 3 and b["name"].lower().startswith("s"))
                )
            )

            send_whatsapp_message(
                user_id,
                f"✅ Saved\n₹{amount}\n{main_name} updated\nTotal balance: ₹{int(total)}"
            )
        else:
            send_whatsapp_message(user_id, response)

        db.commit()
        return JSONResponse({"ok": True})

    except Exception as e:
        # NEVER crash webhook
        print("❌ ERROR:", str(e))
        try:
            send_whatsapp_message(
                user_id,
                "Something went wrong. Please try again."
            )
        except Exception:
            pass

        return JSONResponse({"ok": True})
