from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from app.database import get_db_connection
from app.state_machine import ConversationStateMachine
from app.business_logic import save_entry, get_balances
from app.whatsapp import send_whatsapp_message

app = FastAPI(title="Expense Tracker WhatsApp Bot")


@app.get("/")
def health_check():
    return {"status": "ok", "service": "expense-tracker"}


@app.post("/whatsapp")
async def whatsapp_webhook(request: Request):
    """
    Handles WhatsApp webhook calls.
    Supports:
    - application/x-www-form-urlencoded (Twilio)
    - application/json (Swagger / tests)
    """

    content_type = request.headers.get("content-type", "")

    # ---- Parse incoming message safely ----
    if "application/json" in content_type:
        payload = await request.json()
        msg = str(payload.get("Body", "")).strip().lower()
        user_id = payload.get("From")
    else:
        form = await request.form()
        msg = str(form.get("Body", "")).strip().lower()
        user_id = form.get("From")

    if not user_id:
        return JSONResponse({"error": "Missing user_id"}, status_code=400)

    # ---- DB setup ----
    db = get_db_connection()
    cur = db.cursor(dictionary=True)

    try:
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

        # ---- Basic NLP parsing ----
        parsed = {
            "amount": None,
            "main_category": None,
            "sub_category": None
        }

        for token in msg.split():
            if token.isdigit():
                parsed["amount"] = int(token)

            if token in ("needs", "wants", "savings"):
                parsed["main_category"] = {
                    "needs": 1,
                    "wants": 2,
                    "savings": 3
                }[token]

            if token.isalpha() and token not in (
                "needs", "wants", "savings", "spent", "saved"
            ):
                parsed["sub_category"] = token.capitalize()

        response = fsm.handle_message(msg, parsed)

        # ---- Save entry ----
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
                    main_cat == 1 and b["name"].lower().startswith("n")
                ) or (
                    main_cat == 2 and b["name"].lower().startswith("w")
                ) or (
                    main_cat == 3 and b["name"].lower().startswith("s")
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

    except Exception as e:
        db.rollback()
        return JSONResponse(
            {"error": str(e)},
            status_code=500
        )

    finally:
        cur.close()
        db.close()
