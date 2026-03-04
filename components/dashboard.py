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
db = client[os.getenv("MONGO_DBNAME")]
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


@dashboard_bp.route("/habits/new", methods=["GET"])
@login_required
def add_habit_page():
    '''
    Allows the user to render the add habit page
    '''
    return render_template("addhabits.html")


@dashboard_bp.route("/habits", methods=["POST"])
@login_required
def create_habit():
    """
    Allows the user to create new habits
    """
    data = request.form

    name = (data.get("name") or "").strip()
    category = (data.get("category") or "").strip()
    notes = (data.get("notes") or "").strip()

    habit_type = (data.get("type") or "binary").strip()
    unit = (data.get("unit") or "").strip()
    target_raw = (data.get("target") or "").strip()

    if not name:
        return render_template("addhabits.html", error="Name is required", form=data)

    if habit_type not in {"binary", "count"}:
        return render_template("addhabits.html", error="Invalid habit type", form=data)

    target = None
    if habit_type == "count":
        if not unit:
            return render_template("addhabits.html", error="Unit required for count", form=data)
        if not target_raw:
            return render_template("addhabits.html", error="Target required for count", form=data)
        try:
            target = float(target_raw)
        except ValueError:
            return render_template("addhabits.html", error="Target must be a number", form=data)
        if target <= 0:
            return render_template("addhabits.html", error="Target must be > zero", form=data)

    new_habit = {
        "userId": str(current_user.id),
        "name": name,
        "frequency": "daily",
        "type": habit_type,
        "category": category if category else None,
        "notes": notes if notes else None,
        "unit": unit if habit_type == "count" else None,
        "target": target if habit_type == "count" else None,
        "createdAt": datetime.utcnow(),
        "updatedAt": datetime.utcnow(),
        "archived": False,
    }

    new_habit = {k: v for k, v in new_habit.items() if v is not None}

    habit_collections.insert_one(new_habit)
    return redirect(url_for("dashboard.create_habit_get"))


@dashboard_bp.route("/toggle/<habit_id>", methods=["POST"])
@login_required
def toggle_habit(habit_id):
    user_id = str(current_user.id)
    today_str = datetime.utcnow().strftime("%Y-%m-%d")

    completion = completions_collection.find_one({
        "habitId": habit_id,
        "userId": user_id,
        "date": today_str
    })

    if completion:
        completions_collection.delete_one({"_id": completion["_id"]})
    else:
        completions_collection.insert_one({
            "habitId": habit_id,
            "userId": user_id,
            "date": today_str
        })

    return redirect(url_for("dashboard.dashboard"))


@dashboard_bp.route("/createhabits", methods=["GET"])
@login_required
def create_habit_get():
    user_id = str(current_user.id)

    habits = list(habit_collections.find({
        "userId": user_id,
        "archived": {"$ne": True}
    }))

    for h in habits:
        h["_id"] = str(h["_id"])

    return render_template("habits.html", habits=habits)


@dashboard_bp.route("/edithabit/<habit_id>", methods=["GET", "POST"])
@login_required
def edit_habit(habit_id):
    """
    Allows the user to edit their habits
    """
    user_id = str(current_user.id)

    try:
        oid = ObjectId(habit_id)
    except InvalidId:
        return redirect(url_for("dashboard.create_habit_get"))

    habit = habit_collections.find_one({"_id": oid, "userId": user_id})
    if not habit:
        return redirect(url_for("dashboard.create_habit_get"))

    if request.method == "POST":
        data = request.form

        name = (data.get("name") or "").strip()
        category = (data.get("category") or "").strip()
        notes = (data.get("notes") or "").strip()

        habit_type = (data.get("type") or "binary").strip()
        unit = (data.get("unit") or "").strip()
        target_raw = (data.get("target") or "").strip()

        if not name:
            habit["_id"] = str(habit["_id"])
            habit["type"] = habit.get("type", "binary")
            return render_template("edithabit.html", habit=habit, error="Name is required")

        if habit_type not in {"binary", "count"}:
            habit["_id"] = str(habit["_id"])
            habit["type"] = habit.get("type", "binary")
            return render_template("edithabit.html", habit=habit, error="Invalid habit type")

        target = None
        if habit_type == "count":
            if not unit:
                habit["_id"] = str(habit["_id"])
                habit["type"] = habit.get("type", "binary")
                return render_template("edithabit.html", habit=habit, error="Required for count")
            if not target_raw:
                habit["_id"] = str(habit["_id"])
                habit["type"] = habit.get("type", "binary")
                return render_template("edithabit.html", habit=habit, error="Target required count")
            try:
                target = float(target_raw)
            except ValueError:
                habit["_id"] = str(habit["_id"])
                habit["type"] = habit.get("type", "binary")
                return render_template("edithabit.html", habit=habit, error="Target must be a num")
            if target <= 0:
                habit["_id"] = str(habit["_id"])
                habit["type"] = habit.get("type", "binary")
                return render_template("edithabit.html", habit=habit, error="Target must be > zero")

        set_fields = {
            "name": name,
            "type": habit_type,
            "updatedAt": datetime.utcnow(),
        }

        unset_fields = {}

        if category:
            set_fields["category"] = category
        else:
            unset_fields["category"] = ""

        if notes:
            set_fields["notes"] = notes
        else:
            unset_fields["notes"] = ""

        if habit_type == "count":
            set_fields["unit"] = unit
            set_fields["target"] = target
        else:
            unset_fields["unit"] = ""
            unset_fields["target"] = ""

        update_doc = {"$set": set_fields}
        if unset_fields:
            update_doc["$unset"] = unset_fields

        habit_collections.update_one({"_id": oid, "userId": user_id}, update_doc)

        return redirect(url_for("dashboard.create_habit_get"))

    habit["_id"] = str(habit["_id"])
    habit["type"] = habit.get("type", "binary")
    return render_template("edithabit.html", habit=habit)


@dashboard_bp.route("/habits/<habit_id>/delete", methods=["POST"])
@login_required
def delete_habit(habit_id):
    """
    Allows the user to delete their habits
    """
    user_id = str(current_user.id)

    try:
        oid = ObjectId(habit_id)
    except InvalidId:
        return redirect(url_for("dashboard.dashboard"))

    habit_collections.delete_one({"_id": oid, "userId": user_id})

    completions_collection.delete_many({
        "habitId": habit_id,
        "userId": user_id
    })

    return redirect(url_for("dashboard.dashboard"))


@dashboard_bp.route("/habits/search")
@login_required
def search_habits():
    """
    Allows the user to search for their habits
    """
    user_id = str(current_user.id)
    query = request.args.get("q", "").strip()

    if not query:
        return render_template("search.html", habits=[])

    habits = list(habit_collections.find({
        "userId": user_id,
        "name": {"$regex": query, "$options": "i"},
        "archived": {"$ne": True}
    }))

    for habit in habits:
        habit["_id"] = str(habit["_id"])

    return render_template("search.html", habits=habits)


def calculate_streak(habit_id, user_id):
    ''' 
    Calculates daily streaks from users who do their habits
    '''
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


@dashboard_bp.route("/search")
@login_required
def search_page():
    """
    Search Page
    """
    return render_template("search.html")
