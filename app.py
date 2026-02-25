from bson.objectid import ObjectId
import os
from dotenv import load_dotenv
from flask import  render_template, redirect, url_for, request, Flask
from flask_login import LoginManager, login_user, logout_user, UserMixin, login_required
from db import db, users, habits
from components.dashboard import dashboard_bp

load_dotenv()

def app():
    app = Flask(__name__)

    app.secret_key = os.getenv("SECRET_KEY")

    #link app to dashboard.py
    app.register_blueprint(dashboard_bp)


    app.db = db
    app.users = users
    app.habits = habits

    login_manager = LoginManager()
    login_manager.init_app(app)

    #load in user id after login
    @login_manager.user_loader
    def loadUser(user_id):
        id = users.find_one({"_id": ObjectId(user_id)})
        return id
    
    #catching errors
    # @app.errorhandler(Exception)
    # def handle_exception(e):
    #     return render_template("error.html", error=e)
    
    #for login stuff
    class User(UserMixin):
        pass

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
            return redirect(url_for("dashboard.dashboard"))
        else:
            return render_template("login.html", error="Invalid username or password.")

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
    FLASK_PORT = int(os.getenv("FLASK_PORT", "5000"))
    FLASK_ENV = os.getenv("FLASK_ENV")
    print(f"FLASK_ENV: {FLASK_ENV}, FLASK_PORT: {FLASK_PORT}")
    
    app_instance.run(port=FLASK_PORT)