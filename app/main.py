from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from typing import Optional

from app.database import get_db_connection
from app.state_machine import ConversationStateMachine
from app.business_logic import save_entry, get_balances
from app.whatsapp import send_whatsapp_message

app = FastAPI(
    title="Expense Tracker WhatsApp Bot",
    version="0.1.0"
)

# --------------------------------------------------
# Health Check (VERY IMPORTANT for Railway)
# --------------------------------------------------
@app.get("/")
@app.get("/health")
def health_check():
    return {"status": "ok"}

# --------------------------------------------------
# WhatsApp Webhook
# --------------------------------------------------
@app.post("/whatsapp")
async def whatsapp(request: Request):
    try:
        # --------------------------------------------------
        # 1. Read data (supports Twilio + Swagger + curl)
        # --------------------------------------------------
        content_type = request.headers.get("content-type", "")

        body: Optional[str] = None
        user_id: Optional[str] = None

        if "application/json" in content_type:
            data = await request.json()
            body = data.get("Body") or data.get("body")
            user_id = data.get("From") or data.get("from")
        else:
            data = await request.form()
            body = data.get("Body")
            user_id = data.get("From")

        if not body or not user_id:
            return JSONResponse(
                status_code=200,
                content={"ok": True}
            )

        msg = body.strip().lower()

        # --------------------------------------------------
        # 2. DB Connection
        # --------------------------------------------------
        db = get_db_connection()
        cur = db.cursor(dictionary=True)

        # Ensure user exists
        cur.execute(
            "INSERT IGNORE INTO users (user_id) VALUES (%s)",
            (user_id,)
        )

        # Get conversation state
        cur.execute(
            "SELECT * FROM conversation_state WHERE user_id=%s",
            (user_id,)
        )
        state_row = cur.fetchone()

        fsm = ConversationStateMachine(cur, user_id, state_row)

        # --------------------------------------------------
        # 3. Parse message
        # --------------------------------------------------
        parsed = {
            "amount": None,
            "main_category": None,
            "sub_category": None
        }

        tokens = msg.split()

        for t in tokens:
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

        # --------------------------------------------------
        # 4. FSM Handling
        # --------------------------------------------------
        response = fsm.handle_message(msg, parsed)

        # --------------------------------------------------
        # 5. Save Entry
        # --------------------------------------------------
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
        cur.close()
        db.close()

        return {"ok": True}

    except Exception as e:
        # NEVER crash WhatsApp webhook
        print("❌ ERROR:", e)
        return {"ok": True}
