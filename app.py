"""
MicroHabit Flask application, creates the Flask app, allows us to register, define core routes,
such as login, register, profile, and logout pages.
"""
import os
from typing import Optional
from dotenv import load_dotenv
from bson.objectid import ObjectId
from bson.errors import InvalidId

from flask import Flask, render_template, redirect, url_for, request
from flask_login import (
    LoginManager,
    login_user,
    logout_user,
    UserMixin,
    login_required,
    current_user,
)

from db import db, users, habits
from components.dashboard import dashboard_bp

load_dotenv()


def create_app():
    '''
    Creates and configures Microhabit, it loads, initializes and sets up the flask
    '''
    app = Flask(__name__)

    app.secret_key = os.getenv("SECRET_KEY", "dev-secret")

    app.register_blueprint(dashboard_bp)

    app.db = db
    app.users = users
    app.habits = habits

    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = "login_route"

    class User(UserMixin):
        """ Flask-Login user wrapper around Mongo user document"""
        def __init__(self, user_id: str, username: Optional[str] = None):
            self.id = user_id
            self.username = username

    @login_manager.user_loader
    def load_user(user_id):
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
        return redirect(url_for("login_route"))

    @app.route("/login", methods=["POST", "GET"])
    def login_route():
        if request.method == "GET":
            return render_template("login.html")

        username = request.form.get("username")
        password = request.form.get("password")

        existing_user = users.find_one({"username": username})
        if existing_user and existing_user.get("password") == password:
            user = User(
                user_id=str(existing_user["_id"]),
                username=existing_user.get("username"),
            )

            login_user(user)
            print("I have logged in")
            return redirect(url_for("dashboard.dashboard"))

        return render_template("login.html", error="User/Password")

    @app.route("/register", methods=["POST", "GET"])
    def signup():
        if request.method == "GET":
            return render_template("register.html")

        username = request.form.get("username")
        email = request.form.get("email")
        password = request.form.get("password")

        if users.find_one({"username": username}):
            return render_template("register.html", error="Username already taken")
        if users.find_one({"email": email}):
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

        active_count = habits.count_documents({
            "userId": str(current_user.id),
            "archived": {"$ne": True}
        })

        best_streak = "-"

        member_since = user_doc.get("created_at", "N/A")

        return render_template(
            "profile.html",
            user=user_doc,
            member_since=member_since,
            habit_count=habit_count,
            active_count=active_count,
            best_streak=best_streak,
        )

    @app.route("/profile/edit", methods=["GET", "POST"])
    @login_required
    def edit_profile():
        user_doc = users.find_one({"_id": ObjectId(current_user.id)})
        if not user_doc:
            return redirect(url_for("login_route"))

        if request.method == "GET":
            return render_template("editprofile.html", user=user_doc)

        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip()

        if not username:
            return render_template("editprofile.html", user=user_doc, error="Username is required.")

        if email and ("@" not in email or "." not in email):
            return render_template("editprofile.html", user=user_doc, error="Enter a valid email.")

        users.update_one(
            {"_id": ObjectId(current_user.id)},
            {"$set": {"username": username, "email": email}}
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
    FLASK_PORT = int(os.getenv("FLASK_PORT", "5000"))
    FLASK_ENV = os.getenv("FLASK_ENV")
    print(f"FLASK_ENV: {FLASK_ENV}, FLASK_PORT: {FLASK_PORT}")

    app_instance.run(port=FLASK_PORT)
