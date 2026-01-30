from datetime import date, datetime

VALID_MAIN_CATEGORIES = {
    "1": 1,          # Needs
    "2": 2,          # Wants
    "3": 3,          # Savings
    "needs": 1,
    "wants": 2,
    "savings": 3
}


class ConversationStateMachine:

    def __init__(self, cur, user_id, state_row):
        self.cur = cur
        self.user_id = user_id
        self.state = state_row or self._init_state()

    def _init_state(self):
        self.cur.execute(
            "INSERT IGNORE INTO conversation_state (user_id, state) VALUES (%s,'idle')",
            (self.user_id,)
        )
        self.cur.execute("SELECT * FROM conversation_state WHERE user_id=%s", (self.user_id,))
        return self.cur.fetchone()

    def _update_state(self, **kwargs):
        updates = ", ".join([f"{k}=%s" for k in kwargs])
        values = list(kwargs.values()) + [self.user_id]
        self.cur.execute(
            f"UPDATE conversation_state SET {updates} WHERE user_id=%s",
            values
        )

    # ---------- Global checks ----------
    def is_help(self, msg):
        return msg == "help"

    def is_balance_command(self, msg):
        return msg in ["balance", "needs balance", "wants balance", "savings balance"]

    def is_delete_request(self, msg):
        return msg in ["delete last expense", "delete last"]

    # ---------- Entry ----------
    def handle_message(self, msg, parsed):
        state = self.state["state"]

        if state == "idle":
            return self._idle(parsed)
        if state == "awaiting_amount":
            return self._amount(msg)
        if state == "awaiting_main_category":
            return self._main_category(msg)
        if state == "awaiting_sub_category":
            return self._sub_category(msg)
        if state == "awaiting_date":
            return self._date(msg)
        if state == "confirming_delete":
            return "__CONFIRM_DELETE__" if msg == "yes" else "Cancelled"

        return "Type help for examples"

    # ---------- States ----------
    def _idle(self, parsed):
        if not parsed["amount"]:
            self._update_state(state="awaiting_amount")
            return "Please enter the amount"

        self._update_state(temp_amount=parsed["amount"])

        if not parsed["main_category"]:
            self._update_state(state="awaiting_main_category")
            return "Which category?\n1️⃣ Needs\n2️⃣ Wants\n3️⃣ Savings"

        self._update_state(temp_main_category_id=parsed["main_category"])

        if not parsed["sub_category"]:
            self._update_state(state="awaiting_sub_category")
            return "Which sub-category?"

        self._update_state(temp_sub_category_id=parsed["sub_category"], state="awaiting_date")
        return "Enter date (today / yesterday / YYYY-MM-DD)"

    def _amount(self, msg):
        if not msg.isdigit():
            return "Please enter a valid amount"
        self._update_state(temp_amount=int(msg), state="awaiting_main_category")
        return "Which category?\n1️⃣ Needs\n2️⃣ Wants\n3️⃣ Savings"

    def _main_category(self, msg):
        key = msg.lower()
        if key not in VALID_MAIN_CATEGORIES:
            return "Which category?\n1️⃣ Needs\n2️⃣ Wants\n3️⃣ Savings"

        cat_id = VALID_MAIN_CATEGORIES[key]
        self._update_state(temp_main_category_id=cat_id, state="awaiting_sub_category")

        self.cur.execute("SELECT name FROM main_categories WHERE id=%s", (cat_id,))
        name = self.cur.fetchone()["name"]
        return f"Which sub-category for {name}?"

    def _sub_category(self, msg):
        name = msg.strip().capitalize()

    # Get main category ID from state
        self.cur.execute(
            "SELECT temp_main_category_id FROM conversation_state WHERE user_id=%s",
            (self.user_id,)
        )
        main_cat_id = self.cur.fetchone()["temp_main_category_id"]

    # Check if sub-category exists
        self.cur.execute(
         """
            SELECT id FROM sub_categories
            WHERE name=%s AND main_category_id=%s
        """,
            (name, main_cat_id)
     )
        row = self.cur.fetchone()

    # If not exists, create it
        if not row:
            self.cur.execute(
            """
                INSERT INTO sub_categories (name, main_category_id)
                VALUES (%s,%s)
            """,
                (name, main_cat_id)
            )
            sub_cat_id = self.cur.lastrowid
        else:
            sub_cat_id = row["id"]

    # Store ID, not name
        self._update_state(
            temp_sub_category_id=sub_cat_id,
            state="awaiting_date"
        )

        return "Enter date (today / yesterday / YYYY-MM-DD)"


    def _date(self, msg):
        if msg == "today":
            d = date.today()
        elif msg == "yesterday":
            d = date.today()
        else:
            try:
                d = datetime.strptime(msg, "%Y-%m-%d").date()
            except ValueError:
                return "Enter date (today / yesterday / YYYY-MM-DD)"

        self._update_state(temp_date=d, state="idle")
        return "__SAVE_ENTRY__"
