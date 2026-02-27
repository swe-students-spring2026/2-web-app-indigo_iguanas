import pymongo
from bson.objectid import ObjectId
import datetime
from pymongo.errors import DuplicateKeyError

import os
from dotenv import load_dotenv

from flask import Blueprint, render_template, redirect, url_for, request, jsonify, Flask
from flask_login import login_required, current_user

from db import db, users, habits

from components.dashboard import dashboard_bp

load_dotenv()

def app():
    app = Flask(__name__)

    app.secret_key = os.getenv("SECRET_KEY")

    #link app to dashboard.py
    app.register_blueprint(dashboard_bp)

    #Mongo connection
    from db import db, users, habits

    app.db = db
    app.users = users
    app.habits = habits

    #login stuff
    from flask_login import LoginManager, login_user, logout_user, UserMixin
    login = LoginManager()
    login.init_app(app)


    #for login stuff
    class User(UserMixin):
        pass

    #load in user id after login
    @login.user_loader
    def loadUser(user_id):
        data = users.find_one({"_id": ObjectId(user_id)})
        
        user = User()
        user.id = str(data["_id"])
        user.username = data["username"]

        return user
    
    #catching errors
    # @app.errorhandler(Exception)
    # def handle_exception(e):
    #     return render_template("error.html", error=e)

    @app.route("/")
    def home():
        return redirect(url_for("login"))

    @app.route("/login", methods=["POST", "GET"])
    def login():
        if request.method == "GET":
            return render_template("login.html")

        username = request.form.get("username")
        password = request.form.get("password")
    
        existingUser = users.find_one({"username": username})
        if existingUser and existingUser["password"] == password:
            user = User()
            user.id = str(existingUser["_id"])
            user.username = existingUser["username"]
            
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

        existingUser = users.find_one({"username": username})
        existingEmail= users.find_one({"email": email})

        if existingUser:
            return render_template("register.html", error="Username already exists.")
        if existingEmail:
            return render_template("register.html", error="Email already exists.")
        
        newUser = {
            "username": username,
            "email": email,
            "password": password
        }

        users.insert_one(newUser)

        return render_template("login.html", message="Registration complete! Please log in.")

    #logout stuff
    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        return redirect(url_for("login"))
    return app

app_instance = app()

#I have no idea what this is but it seems necessary 
#lowk copy pasted professors code from example app 
if __name__ == "__main__":
    FLASK_PORT = os.getenv("FLASK_PORT", "5000")
    FLASK_ENV = os.getenv("FLASK_ENV")
    print(f"FLASK_ENV: {FLASK_ENV}, FLASK_PORT: {FLASK_PORT}")

    app_instance.run(port=FLASK_PORT) 

    