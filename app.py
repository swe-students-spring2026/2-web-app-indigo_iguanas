import os 
from dotenv import load_dotenv
from bson.objectid import ObjectId

from flask import Flask, render_template, redirect, url_for, request
from flask_login import LoginManager, login_user, logout_user, UserMixin, login_required, current_user

from db import db, users, habits 
from components.dashboard import dashboard_bp

load_dotenv()

def app():
    app = Flask(__name__)

    app.secret_key = os.getenv("SECRET_KEY", "dev-secret")

    #link app to dashboard.py
    app.register_blueprint(dashboard_bp)

    app.db = db
    app.users = users
    app.habits = habits

    #login stuff
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = "login_route"

    #for login stuff
    class User(UserMixin):
        pass

    #load in user id after login
    @login_manager.user_loader
    def load_user(user_id):
        try:
            data = users.find_one({"_id": ObjectId(user_id)})
        except Exception:
            return None
        if not data:
            return None

        user = User()
        user.id = str(data["_id"])
        user.username = data.get("username")
        return user

    @app.route("/")
    def home():
        return redirect(url_for("login_route"))

    @app.route("/login", methods=["POST", "GET"])
    def login_route():
        if request.method == "GET":
            return render_template("login.html")

        username = request.form.get("username")
        password = request.form.get("password")
    
        existingUser = users.find_one({"username": username})
        if existingUser and existingUser.get("password") == password:
            user = User()
            user.id = str(existingUser["_id"])
            user.username = existingUser.get("username")
            
            login_user(user)
            print("I have logged in")
            return redirect(url_for("dashboard.dashboard"))
        else:
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
        
        users.insert_one({"username": username, "email":email, "password":password})
        return render_template("login.html", message="Registration complete! Please login.")
    

    ##### user profile page

    @app.route("/profile")
    @login_required
    def profile():
        # get the user's document from Mongo
        user_doc = users.find_one({"_id": ObjectId(current_user.id)})

        if not user_doc:
            # if somehow the session exists but the user doesn't
            return redirect(url_for("login_route"))

       
        habit_count = habits.count_documents({"userId": str(current_user.id)})

        active_count = habits.count_documents({
            "userId": str(current_user.id),
            "archived": {"$ne": True}
        })

        best_streak = "—"

        member_since = user_doc.get("created_at", "N/A")

        return render_template(
            "profile.html",
            user=user_doc,
            member_since=member_since,
            habit_count=habit_count,
            active_count=active_count,
            best_streak=best_streak,
        )
    

    ##### edit profile 

    @app.route("/profile/edit", methods=["GET", "POST"])
    @login_required
    def edit_profile():
        user_doc = users.find_one({"_id": ObjectId(current_user.id)})
        if not user_doc:
            return redirect(url_for("login_route"))

        if request.method == "GET":
            return render_template("editprofile.html", user=user_doc)

        # --- POST: update username/email + optional password change
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip()

        current_password = (request.form.get("current_password") or "")
        new_password = (request.form.get("new_password") or "")
        confirm_password = (request.form.get("confirm_password") or "")

        # basic validation for profile fields
        if not username:
            return render_template("editprofile.html", user=user_doc, error="Username is required.")

        if email and ("@" not in email or "." not in email):
            return render_template("editprofile.html", user=user_doc, error="Enter a valid email.")

        update_fields = {"username": username, "email": email}

        wants_password_change = bool(new_password or confirm_password or current_password)

        if wants_password_change:
            if not current_password or not new_password or not confirm_password:
                return render_template(
                    "editprofile.html",
                    user=user_doc,
                    error="To change your password, fill out current, new, and confirm password."
                )

            if user_doc.get("password") != current_password:
                return render_template(
                    "editprofile.html",
                    user=user_doc,
                    error="Current password is incorrect."
                )

            if new_password != confirm_password:
                return render_template(
                    "editprofile.html",
                    user=user_doc,
                    error="New password and confirmation do not match."
                )

            if len(new_password) < 6:
                return render_template(
                    "editprofile.html",
                    user=user_doc,
                    error="New password must be at least 6 characters."
                )

            update_fields["password"] = new_password

        users.update_one(
            {"_id": ObjectId(current_user.id)},
            {"$set": update_fields}
        )

        return redirect(url_for("profile"))

    #logout stuff
    @app.route("/logout")
    @login_required
    def logout_route():
        logout_user()
        return redirect(url_for("login_route"))
    return app

app_instance = app()

#I have no idea what this is but it seems necessary 
#lowk copy pasted professors code from example app 
if __name__ == "__main__":
    FLASK_PORT = int(os.getenv("FLASK_PORT", "5000"))
    FLASK_ENV = os.getenv("FLASK_ENV")
    print(f"FLASK_ENV: {FLASK_ENV}, FLASK_PORT: {FLASK_PORT}")

    app_instance.run(port=FLASK_PORT) 


