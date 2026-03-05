"""
MicroHabit Flask application. Creates the Flask app and defines core routes,
such as login, register, profile, edit profile, and logout.
"""

import os
from typing import Optional

from bson.errors import InvalidId
from bson.objectid import ObjectId
from dotenv import load_dotenv
from flask import Flask, redirect, render_template, request, url_for
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)

from components.dashboard import dashboard_bp
from db import db, habits, users

load_dotenv()


class User(UserMixin):
    """Flask-Login user wrapper around Mongo user document."""

    def __init__(self, user_id: str, username: Optional[str] = None):
        self.id = user_id
        self.username = username


def create_app() -> Flask:
    """
    Creates and configures the MicroHabit Flask app.
    """
    app = Flask(__name__)
    app.secret_key = os.getenv("SECRET_KEY", "dev-secret")

    # Attach db handles if you want them accessible via app.*
    app.db = db
    app.users = users
    app.habits = habits

    # Register blueprints
    app.register_blueprint(dashboard_bp)

    # Login manager setup
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = "login_route"

    @login_manager.user_loader
    def load_user(user_id: str):
        try:
            data = users.find_one({"_id": ObjectId(user_id)})
        except (InvalidId, TypeError):
            return None

        if not data:
            return None

        return User(
            user_id=str(data["_id"]),
            username=data.get("username"),
        )

    @app.route("/")
    def home():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard.dashboard"))
        return redirect(url_for("login_route"))

    @app.route("/login", methods=["GET", "POST"])
    def login_route():
        if request.method == "GET":
            return render_template("login.html")

        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        existing_user = users.find_one({"username": username})
        if existing_user and existing_user.get("password") == password:
            user = User(
                user_id=str(existing_user["_id"]),
                username=existing_user.get("username"),
            )
            login_user(user)
            return redirect(url_for("dashboard.dashboard"))

        return render_template("login.html", error="User/Password")

    @app.route("/register", methods=["GET", "POST"])
    def signup():
        if request.method == "GET":
            return render_template("register.html")

        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""

        if not username:
            return render_template("register.html", error="Username is required.")
        if not password:
            return render_template("register.html", error="Password is required.")
        if email and ("@" not in email or "." not in email):
            return render_template("register.html", error="Enter a valid email.")

        if users.find_one({"username": username}):
            return render_template("register.html", error="Username already taken")
        if email and users.find_one({"email": email}):
            return render_template("register.html", error="Email already exists.")

        users.insert_one({"username": username, "email": email, "password": password})
        return render_template("login.html", message="Registration complete! Please login.")

    @app.route("/profile")
    @login_required
    def profile():
        user_doc = users.find_one({"_id": ObjectId(current_user.id)})
        if not user_doc:
            return redirect(url_for("login_route"))

        habit_count = habits.count_documents({"userId": str(current_user.id)})
        active_count = habits.count_documents(
            {"userId": str(current_user.id), "archived": {"$ne": True}}
        )

        best_streak = "-"
        member_since = user_doc.get("created_at", "N/A")

        return render_template(
            "profile.html",
            user=user_doc,
            habit_count=habit_count,
            active_count=active_count,
            best_streak=best_streak,
            member_since=member_since,
        )

    @app.route("/profile/edit", methods=["GET", "POST"])
    @login_required
    def edit_profile():
        user_doc = users.find_one({"_id": ObjectId(current_user.id)})
        if not user_doc:
            return redirect(url_for("login_route"))

        if request.method == "GET":
            return render_template("editprofile.html", user=user_doc)

        # POST: update username/email + optional password change
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip()

        current_password = request.form.get("current_password") or ""
        new_password = request.form.get("new_password") or ""
        confirm_password = request.form.get("confirm_password") or ""

        if not username:
            return render_template(
                "editprofile.html", user=user_doc, error="Username is required."
            )

        if email and ("@" not in email or "." not in email):
            return render_template(
                "editprofile.html", user=user_doc, error="Enter a valid email."
            )

        update_fields = {"username": username, "email": email}

        wants_password_change = bool(current_password or new_password or confirm_password)
        if wants_password_change:
            if not (current_password and new_password and confirm_password):
                return render_template(
                    "editprofile.html",
                    user=user_doc,
                    error="To change your password, fill out current, new, and confirm password.",
                )

            if user_doc.get("password") != current_password:
                return render_template(
                    "editprofile.html",
                    user=user_doc,
                    error="Current password is incorrect.",
                )

            if new_password != confirm_password:
                return render_template(
                    "editprofile.html",
                    user=user_doc,
                    error="New password and confirmation do not match.",
                )

            if len(new_password) < 6:
                return render_template(
                    "editprofile.html",
                    user=user_doc,
                    error="New password must be at least 6 characters.",
                )

            update_fields["password"] = new_password

        users.update_one(
            {"_id": ObjectId(current_user.id)},
            {"$set": update_fields},
        )

        return redirect(url_for("profile"))

    @app.route("/logout")
    @login_required
    def logout_route():
        logout_user()
        return redirect(url_for("login_route"))

    return app


app_instance = create_app()

if __name__ == "__main__":
    flask_port = int(os.getenv("FLASK_PORT", "5000"))
    flask_env = os.getenv("FLASK_ENV")
    print(f"FLASK_ENV: {flask_env}, FLASK_PORT: {flask_port}")
    app_instance.run(port=flask_port)
    