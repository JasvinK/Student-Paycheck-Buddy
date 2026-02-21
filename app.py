from flask import Flask, render_template, request, redirect, url_for, session, flash, g
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import os
from datetime import date, datetime, timedelta

from config import Config

DEFAULT_CATEGORIES = [
    "Rent", "Groceries", "Transit", "Tuition", "Textbooks",
    "Phone", "Subscriptions", "Eating Out", "Coffee", "Entertainment", "Other"
]

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    os.makedirs(os.path.join(os.path.dirname(__file__), "instance"), exist_ok=True)

    # -------- DB helpers --------
    def get_db():
        if "db" not in g:
            g.db = sqlite3.connect(app.config["DATABASE"])
            g.db.row_factory = sqlite3.Row
            g.db.execute("PRAGMA foreign_keys = ON;")
        return g.db

    @app.teardown_appcontext
    def close_db(_exc):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    def init_db():
        db = get_db()
        schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
        with open(schema_path, "r", encoding="utf-8") as f:
            db.executescript(f.read())
        db.commit()

    def ensure_db():
        db_path = app.config["DATABASE"]
        # If DB file doesn't exist, create it + tables
        if not os.path.exists(db_path):
            init_db()
            return

        # If DB exists but tables are missing, create them
        try:
            db = get_db()
            db.execute("SELECT 1 FROM users LIMIT 1;")
        except sqlite3.OperationalError:
            init_db()

    ensure_db()

    @app.route("/init")
    def init():
        init_db()
        return "DB initialized. Go to /signup"

    # -------- Auth helpers --------
    def current_user_id():
        return session.get("user_id")

    def require_login():
        if not current_user_id():
            flash("Please log in first.")
            return False
        return True

    # -------- Date & money helpers --------
    def parse_ymd(s: str) -> date:
        return datetime.strptime(s, "%Y-%m-%d").date()

    def ymd(d: date) -> str:
        return d.strftime("%Y-%m-%d")

    def cents_from_money_str(x: str) -> int:
        x = x.strip()
        if not x:
            return 0
        if "." in x:
            dollars, cents = x.split(".", 1)
            cents = (cents + "00")[:2]
        else:
            dollars, cents = x, "00"
        return int(dollars) * 100 + int(cents)

    def money_from_cents(c: int) -> str:
        sign = "-" if c < 0 else ""
        c = abs(c)
        return f"{sign}{c//100}.{c%100:02d}"

    # -------- Pay schedule helpers --------
    def get_schedule(user_id: int):
        db = get_db()
        return db.execute("SELECT * FROM pay_schedules WHERE user_id = ?", (user_id,)).fetchone()

    def current_pay_period(schedule_row):
        next_payday = parse_ymd(schedule_row["next_payday"])
        period_end = next_payday - timedelta(days=1)
        period_start = period_end - timedelta(days=13)
        return period_start, period_end, next_payday

    # -------- Routes --------
    @app.route("/")
    def home():
        if current_user_id():
            return redirect(url_for("dashboard"))
        return redirect(url_for("login"))

    @app.route("/signup", methods=["GET", "POST"])
    def signup():
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            pw = request.form.get("password", "")

            if not email or not pw:
                flash("Email and password required.")
                return render_template("auth_signup.html")

            db = get_db()
            try:
                db.execute(
                    "INSERT INTO users (email, password_hash) VALUES (?, ?)",
                    (email, generate_password_hash(pw))
                )
                db.commit()
            except sqlite3.IntegrityError:
                flash("That email is already registered.")
                return render_template("auth_signup.html")

            user = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            session["user_id"] = user["id"]
            return redirect(url_for("setup"))

        return render_template("auth_signup.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            pw = request.form.get("password", "")

            db = get_db()
            user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

            if not user or not check_password_hash(user["password_hash"], pw):
                flash("Invalid login.")
                return render_template("auth_login.html")

            session["user_id"] = user["id"]

            if not get_schedule(user["id"]):
                return redirect(url_for("setup"))
            return redirect(url_for("dashboard"))

        return render_template("auth_login.html")

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/setup", methods=["GET", "POST"])
    def setup():
        if not require_login():
            return redirect(url_for("login"))

        user_id = current_user_id()
        db = get_db()

        if request.method == "POST":
            next_payday = request.form.get("next_payday", "").strip()
            net_pay = request.form.get("typical_net_pay", "").strip()

            try:
                _ = parse_ymd(next_payday)
            except Exception:
                flash("Next payday must be YYYY-MM-DD.")
                return render_template("setup.html", categories=DEFAULT_CATEGORIES)

            net_pay_cents = cents_from_money_str(net_pay)

            db.execute("""
                INSERT INTO pay_schedules (user_id, frequency, next_payday, typical_net_pay_cents)
                VALUES (?, 'biweekly', ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    next_payday=excluded.next_payday,
                    typical_net_pay_cents=excluded.typical_net_pay_cents
            """, (user_id, next_payday, net_pay_cents))
            db.commit()

            flash("Setup saved!")
            return redirect(url_for("dashboard"))

        return render_template("setup.html", categories=DEFAULT_CATEGORIES)

    @app.route("/dashboard")
    def dashboard():
        if not require_login():
            return redirect(url_for("login"))

        user_id = current_user_id()
        db = get_db()

        schedule = get_schedule(user_id)
        if not schedule:
            return redirect(url_for("setup"))

        start, end, next_payday = current_pay_period(schedule)

        # --- totals for this pay period ---
        rows = db.execute("""
            SELECT kind, SUM(amount_cents) AS total
            FROM transactions
            WHERE user_id = ?
              AND occurred_on BETWEEN ? AND ?
            GROUP BY kind
        """, (user_id, ymd(start), ymd(end))).fetchall()

        totals = {"income": 0, "expense": 0}
        for r in rows:
            totals[r["kind"]] = r["total"] or 0

        typical = schedule["typical_net_pay_cents"]
        remaining = typical + totals["income"] - totals["expense"]

        # --- bills due before next payday ---
        bills = db.execute("""
            SELECT name, amount_cents, due_day
            FROM recurring_bills
            WHERE user_id = ? AND active = 1
            ORDER BY due_day ASC
        """, (user_id,)).fetchall()

        today = date.today()
        due_before = []
        total_due_cents = 0

        for b in bills:
            due_day = b["due_day"]

            # last day of current month
            first_next_month = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
            last_day = (first_next_month - timedelta(days=1)).day
            actual_day = min(due_day, last_day)
            due_date = today.replace(day=actual_day)

            # if already passed, move to next month
            if due_date < today:
                next_month = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
                first_next_next = (next_month + timedelta(days=32)).replace(day=1)
                last_day_nm = (first_next_next - timedelta(days=1)).day
                actual_day_nm = min(due_day, last_day_nm)
                due_date = next_month.replace(day=actual_day_nm)

            if due_date < next_payday:
                due_before.append({
                    "name": b["name"],
                    "amount": money_from_cents(b["amount_cents"]),
                    "due": ymd(due_date)
                })
                total_due_cents += b["amount_cents"]

        after_bills_cents = remaining - total_due_cents

        # --- daily spend limit ---
        days_left = (end - today).days + 1
        if days_left < 1:
            days_left = 1
        daily_limit = remaining // days_left

        # --- top category this pay period ---
        top = db.execute("""
            SELECT category, SUM(amount_cents) AS total
            FROM transactions
            WHERE user_id = ?
              AND kind = 'expense'
              AND occurred_on BETWEEN ? AND ?
            GROUP BY category
            ORDER BY total DESC
            LIMIT 1
        """, (user_id, ymd(start), ymd(end))).fetchone()

        return render_template(
            "dashboard.html",
            period_start=ymd(start),
            period_end=ymd(end),
            next_payday=ymd(next_payday),
            typical=money_from_cents(typical),
            income=money_from_cents(totals["income"]),
            expense=money_from_cents(totals["expense"]),
            remaining=money_from_cents(remaining),
            daily_limit=money_from_cents(daily_limit),
            top_category=(top["category"] if top else None),
            top_total=(money_from_cents(top["total"]) if top else None),
            bills_due=due_before,
            bills_total=money_from_cents(total_due_cents),
            after_bills=money_from_cents(after_bills_cents),
        )

    
    @app.route("/transactions")
    def transactions():
        if not require_login():
            return redirect(url_for("login"))

        user_id = current_user_id()
        db = get_db()

        category = request.args.get("category", "").strip()
        kind = request.args.get("kind", "").strip()

        query = "SELECT * FROM transactions WHERE user_id = ?"
        params = [user_id]

        if kind in ("income", "expense"):
            query += " AND kind = ?"
            params.append(kind)

        if category:
            query += " AND category = ?"
            params.append(category)

        query += " ORDER BY occurred_on DESC, id DESC LIMIT 200"
        rows = db.execute(query, tuple(params)).fetchall()

        return render_template("transactions.html", rows=rows)


    @app.route("/transactions/new", methods=["GET", "POST"])
    def transaction_new():
        if not require_login():
            return redirect(url_for("login"))

        if request.method == "POST":
            user_id = current_user_id()
            kind = request.form.get("kind", "expense")
            amount = request.form.get("amount", "0")
            category = request.form.get("category", "Other").strip()
            occurred_on = request.form.get("occurred_on", ymd(date.today())).strip()
            note = request.form.get("note", "").strip()

            if kind not in ("income", "expense"):
                flash("Invalid type.")
                return redirect(url_for("transaction_new"))

            try:
                _ = parse_ymd(occurred_on)
            except Exception:
                flash("Date must be YYYY-MM-DD.")
                return redirect(url_for("transaction_new"))

            amount_cents = cents_from_money_str(amount)

            db = get_db()
            db.execute("""
                INSERT INTO transactions (user_id, kind, amount_cents, category, occurred_on, note)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, kind, amount_cents, category, occurred_on, note))
            db.commit()

            flash("Transaction added!")
            return redirect(url_for("transactions"))

        return render_template(
            "transaction_form.html",
            categories=DEFAULT_CATEGORIES,
            default_date=ymd(date.today())
        )


    @app.route("/budgets", methods=["GET", "POST"])
    def budgets():
        if not require_login():
            return redirect(url_for("login"))

        user_id = current_user_id()
        db = get_db()

        if request.method == "POST":
            category = request.form.get("category", "Other").strip()
            limit = request.form.get("limit", "0").strip()
            limit_cents = cents_from_money_str(limit)

            db.execute("""
                INSERT INTO budgets (user_id, category, limit_cents)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id, category) DO UPDATE SET limit_cents=excluded.limit_cents
            """, (user_id, category, limit_cents))
            db.commit()

            flash("Budget saved!")
            return redirect(url_for("budgets"))

        # get schedule to compute current pay period spending
        schedule = get_schedule(user_id)
        start, end, _ = current_pay_period(schedule) if schedule else (None, None, None)

        # budgets list
        budget_rows = db.execute("""
            SELECT category, limit_cents
            FROM budgets
            WHERE user_id = ?
            ORDER BY category
        """, (user_id,)).fetchall()

        # spending per category in current pay period
        spent_map = {}
        if start and end:
            spent_rows = db.execute("""
                SELECT category, SUM(amount_cents) AS spent
                FROM transactions
                WHERE user_id = ?
                  AND kind = 'expense'
                  AND occurred_on BETWEEN ? AND ?
                GROUP BY category
            """, (user_id, ymd(start), ymd(end))).fetchall()

            for r in spent_rows:
                spent_map[r["category"]] = r["spent"] or 0

        # merge into a list for the template
        items = []
        for b in budget_rows:
            cat = b["category"]
            limit_cents = b["limit_cents"]
            spent_cents = spent_map.get(cat, 0)
            remaining_cents = limit_cents - spent_cents
            pct = 0
            status = "ok"
            if limit_cents > 0:
                pct_raw = int((spent_cents / limit_cents) * 100)
                pct = min(100, pct_raw)
            if pct_raw >= 100:
                status = "over"
            elif pct_raw >= 80:
                status = "warn"

            items.append({
                "category": cat,
                "limit": money_from_cents(limit_cents),
                "spent": money_from_cents(spent_cents),
                "remaining": money_from_cents(remaining_cents),
                "pct": pct,
                "status": status
            })

        return render_template("budgets.html", items=items, categories=DEFAULT_CATEGORIES)

    @app.route("/bills", methods=["GET", "POST"])
    def bills():
            if not require_login():
                return redirect(url_for("login"))

            user_id = current_user_id()
            db = get_db()

            if request.method == "POST":
                name = request.form.get("name", "").strip()
                amount = request.form.get("amount", "0").strip()
                due_day = request.form.get("due_day", "1").strip()

                if not name:
                    flash("Bill name required.")
                    return redirect(url_for("bills"))

                try:
                    due_day_int = int(due_day)
                except:
                    flash("Due day must be a number 1–31.")
                    return redirect(url_for("bills"))

                if due_day_int < 1 or due_day_int > 31:
                    flash("Due day must be between 1 and 31.")
                    return redirect(url_for("bills"))

                amount_cents = cents_from_money_str(amount)

                db.execute("""
                    INSERT INTO recurring_bills (user_id, name, amount_cents, due_day, active)
                    VALUES (?, ?, ?, ?, 1)
                """, (user_id, name, amount_cents, due_day_int))
                db.commit()

                flash("Bill added!")
                return redirect(url_for("bills"))

            rows = db.execute("""
                SELECT id, name, amount_cents, due_day, active
                FROM recurring_bills
                WHERE user_id = ? AND active = 1
                ORDER BY due_day ASC, name ASC
            """, (user_id,)).fetchall()

            return render_template("bills.html", rows=rows)

    return app

if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)

