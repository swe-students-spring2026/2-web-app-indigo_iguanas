'''
Dashboard blueprints and routes for the Web App: Microhabit 
'''

import os
from datetime import datetime, timedelta
from flask import Blueprint, render_template, redirect, url_for, request
from flask_login import login_required, current_user
from pymongo import MongoClient
from bson.objectid import ObjectId
from bson.errors import InvalidId
from dotenv import load_dotenv

load_dotenv()

dashboard_bp = Blueprint("dashboard", __name__)

#Mongo Setup
client = MongoClient(os.getenv("MONGO_URI"))
db = client["microhabit"]
habit_collections = db["habits"]
completions_collection = db["completions"]

#Dashboard view
@dashboard_bp.route("/dashboard")
@login_required
def dashboard():
    """
    Displays today's habits for the logged in user.
    """

    user_id = str(current_user.id)

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

# Create Habit Post
@dashboard_bp.route("/createhabits", methods=["POST"])
@login_required
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


# Create Habit Get
@dashboard_bp.route("/createhabits", methods=["GET"])
@login_required
def create_habit_get():
    user_id = str(current_user.id)

    habits = list(habit_collections.find({
        "userId": user_id,
        "archived": {"$ne": True}
    }))

    for h in habits:
        h['_id'] = str(h['_id'])

    return render_template('habits.html', habits=habits)

# Toggle Completion


# Edit Habit
@dashboard_bp.route("/edithabit/<habit_id>", methods=["GET","POST"])
@login_required
def edit_habit(habit_id):
    user_id = str(current_user.id)

    try:
        oid = ObjectId(habit_id)
    except InvalidId:
        return redirect(url_for("dashboard.viewhabits"))

    habit = habit_collections.find_one({
        "_id": oid,
        "userId": user_id
    })

    if not habit:
        return redirect(url_for("dashboard.viewhabits"))

    if request.method == "POST":
        data = request.form

        name = (data.get("name") or "").strip()

        updated_fields = {
            "name":name,
            "frequency":data.get("frequency") or habit.get('frequency', 'daily'),
            'updatedAt':datetime.utcnow()
        }

        if not updated_fields["name"]:
            return render_template("edithabit.html", habit=habit, error="name is required")

        habit_collections.update_one(
            {"_id": oid, "userId": user_id},
            {"$set":updated_fields}
        )
        return redirect(url_for("dashboard.viewhabits"))

    habit["_id"] = str(habit["_id"])
    return render_template("edithabit.html", habit=habit)


# Delete Habit
@dashboard_bp.route("/habits/<habit_id>/delete", methods=["POST"])
@login_required
def delete_habit(habit_id):
    user_id = str(current_user.id)

    try:
        oid = ObjectId(habit_id)
    except InvalidId:
        return redirect(url_for("dashboard.dashboard"))

    habit_collections.delete_one({
        "_id": oid,
        "userId": user_id
    })

    completions_collection.delete_many({
        "habitId": habit_id,
        "userId": user_id
    })

    return redirect(url_for("dashboard.dashboard"))

# Search Habit
@dashboard_bp.route("/habits/search")
@login_required
def search_habits():
    user_id = str(current_user.id)
    query = request.args.get("q", "").strip()

    if not query:
        return render_template("search_results.html", habits=[])
    
    habits = list(habit_collections.find({
        "userId": user_id,
        "name": {"$regex": query, "$options": "i"},
        "archived": {"$ne": True}
    })

    for habit in habits:
        habit["_id"] = str(habit["_id"])
        
    return render_template("search_results.html", habits=habits)

# View Habits





# Streak Calculations
def calculate_streak(habit_id, user_id):

    #Calculates consecutive daily streak ending today.

    today = datetime.utcnow().date()
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
            today = today - timedelta(days=1)
        else:
            break

    return streak
