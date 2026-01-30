from datetime import date

def is_savings(cur, main_cat_id):
    cur.execute("SELECT name FROM main_categories WHERE id=%s", (main_cat_id,))
    return cur.fetchone()["name"] == "Savings"


def save_entry(cur, user_id, state):
    amount = state["temp_amount"]
    main_cat = state["temp_main_category_id"]
    sub_cat = state["temp_sub_category_id"]
    entry_date = state["temp_date"] or date.today()

    entry_type = "SAVING" if is_savings(cur, main_cat) else "EXPENSE"

    cur.execute(
        """INSERT INTO expenses
        (user_id, main_category_id, sub_category_id, amount, entry_type, expense_date)
        VALUES (%s,%s,%s,%s,%s,%s)""",
        (user_id, main_cat, sub_cat, amount, entry_type, entry_date)
    )

    cur.execute(
        "UPDATE users SET total_balance = total_balance - %s WHERE user_id=%s",
        (amount, user_id)
    )

    cur.execute(
        """INSERT INTO category_balances
        (user_id, main_category_id, sub_category_id, balance)
        VALUES (%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE balance = balance - %s""",
        (user_id, main_cat, sub_cat, amount, amount)
    )

    cur.execute(
        """UPDATE conversation_state
        SET temp_amount=NULL, temp_main_category_id=NULL,
            temp_sub_category_id=NULL, temp_date=NULL
        WHERE user_id=%s""",
        (user_id,)
    )

    return amount, main_cat


def get_balances(cur, user_id):
    cur.execute(
        """SELECT mc.name, SUM(cb.balance) bal
           FROM category_balances cb
           JOIN main_categories mc ON mc.id = cb.main_category_id
           WHERE cb.user_id=%s
           GROUP BY mc.name""",
        (user_id,)
    )
    return cur.fetchall()
