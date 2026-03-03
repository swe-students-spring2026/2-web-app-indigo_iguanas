from flask import Blueprint, render_template, redirect, url_for, request, jsonify
from flask_login import login_required, current_user
from pymongo import MongoClient
from bson.objectid import ObjectId
from datetime import datetime
import os
from dotenv import load_dotenv
from datetime import timedelta
load_dotenv()

dashboard_bp = Blueprint("dashboard", __name__)

#Mongo Setup
client = MongoClient(os.getenv("Mongo_URI"))
db = client[os.getenv("MONGO_DBNAME")]
habit_collections = db["habits"]
completions_collection = db["completions"]

#Dashboard view 
@dashboard_bp.route("/dashboard")
#@login_required
def dashboard():
    """
    Displays today's habits for the logged in user.
    """

    # FOR LATER USE user_id = str(current_user.id)
    user_id = "testuser"

    habits = list(habit_collections.find({
        "userId": user_id,
        "archived": {"$ne": True}
    }))

    today_str = datetime.utcnow().strftime("%Y-%m-%d")

    for habit in habits:
        habit["_id"] = str(habit["_id"])

        completion = completions_collection.find_one({
            "habitId": habit["_id"],
            "userId": user_id,
            "date": today_str
        })

        habit["completed_today"] = completion is not None
        habit["streak"] = calculate_streak(habit["_id"], user_id)

    return render_template("dashboard.html", habits=habits)

# Create Habit
@dashboard_bp.route("/habits", methods=["POST"])
#@login_required
def create_habit():
    data = request.form

    new_habit = {
        "userId": str(current_user.id),
        "name": data.get("name"),
        "frequency": "daily",
        "createdAt": datetime.utcnow(),
        "archived": False
    }

    habit_collections.insert_one(new_habit)
    return redirect(url_for("dashboard.dashboard"))


# Create Habit


# Toggle Completion


# Edit Habit

# Delete Habit 
@dashboard_bp.route("/habits/<habit_id>/delete", methods=["POST"])
#@login_required
def delete_habit(habit_id):
    return redirect(url_for("dashboard.dashboard"))

# Search Habit 
@dashboard_bp.route("/habits/search")
#@login_required
def search_habits():
    #SAFE FOR LATER return render_template("search_results.html", habits=habits)
    return "Search not implemented yet"


# Streak Calculations 
def calculate_streak(habit_id, user_id):
    
    #Calculates consecutive daily streak ending today.

    today = datetime.now().date()
    streak = 0

    while True:
        date_str = today.strftime("%Y-%m-%d")

        exists = completions_collection.find_one({
            "habitId": habit_id,
            "userId": user_id,
            "date": date_str
        })

        if exists:
            streak += 1
            today = today.replace(day=today.day - 1)
        else:
            break

    return streak