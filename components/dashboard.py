'''
Dashboard blueprints and routes for the Web App: Microhabit 
'''

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Blueprint, render_template, redirect, url_for, request
from flask_login import login_required, current_user
from pymongo import MongoClient
from bson.objectid import ObjectId
from bson.errors import InvalidId
from dotenv import load_dotenv

load_dotenv()

dashboard_bp = Blueprint("dashboard", __name__)

def today_str_local():
    '''
    This is to use local dates for the streaks to match their expectations 
    '''
    return datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")

#Mongo Setup
client = MongoClient(os.getenv("MONGO_URI"))
db = client[os.getenv("MONGO_DBNAME")]
habit_collections = db["habits"]
completions_collection = db["completions"]
users_collection = db["users"]

def parse_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

def parse_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

def should_show_today(habit, today_dt):
    schedule = habit.get("schedule") or {}
    schedule_type = schedule.get("type", habit.get("frequency", "daily"))

    if schedule_type == "daily":
        return True 
    
    if schedule_type in {"weekly", "biweekly"}:
        interval = 7 if schedule_type == "weekly" else 14
        start_str = schedule.get("start_date")

        if not start_str:
            created = habit.get("createdAt")
            if created and hasattr(created, "strftime"):
                start_str = created.strftime("%Y-%m-%d")
            
            if not start_str:
                return True
            
            try:
                start_dt = datetime.striptime(start_str, "%Y-%m-%d").date()
            except Exception:
                return True
            
            delta = (today_dt - start_dt).days
            return delta >= 0 and (delta % interval == 0)
        
        if schedule_type == "monthly":
            start_str = schedule.get("start_date")
            if not start_str:
                created = habit.get("createdAt")
                if created and hasattr(created, "shrftime"):
                    start_str = created.strftime("%Y-%m-%d")
            day =1 



@dashboard_bp.route("/dashboard")
@login_required
def dashboard():
    user_id = str(current_user.id)
    today_str = today_str_local()
    today_dt = datetime.now(ZoneInfo("America/New_York")).date()

    habits = list(habit_collections.find({
        "userId": user_id,
        "archived": {"$ne": True}
    }))

    due_habits = []
    for habit in habits:
        habit["_id"] = str(habit["_id"])

        if not should_show_today(habit, today_dt):
            continue

        completion = completions_collection.find_one({
            "habitId": habit["_id"],
            "userId": user_id,
            "date": today_str
        })

        habit["completed_today"] = completion is not None
        habit["streak"] = calculate_streak(habit["_id"], user_id)

        due_habits.append(habit)

    done_habits = [h for h in due_habits if h.get("completed_today")]
    not_done_habits = [h for h in due_habits if not h.get("completed_today")]

    return render_template(
        "dashboard.html",
        habits=due_habits,
        done_habits=done_habits,
        not_done_habits=not_done_habits,
        today_str=today_str
    )


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
    Allow user to create habits
    """
    data = request.form
    user_id = str(current_user.id)

    name = (data.get("name") or "").strip()
    category = (data.get("category") or "").strip()
    notes = (data.get("notes") or "").strip()

    schedule_type = (data.get("schedule_type") or "daily").strip()
    custom_days_raw = data.getlist("custom_days")
    custom_days = [d for d in (parse_int(x, None) for x in custom_days_raw) if d is not None]

    if schedule_type not in {"daily", "weekly", "biweekly", "monthly", "custom"}:
        schedule_type = "daily"

    if schedule_type == "custom" and not custom_days:
        custom_days = [0, 1, 2, 3, 4]

    schedule_doc = {
        "type": schedule_type,
        "start_date": today_str_local()
    }
    if schedule_type == "custom":
        schedule_doc["custom_days"] = sorted(list(set(custom_days)))

    goal_value_raw = (data.get("goal_value") or "").strip()
    goal_unit = (data.get("goal_unit") or "times").strip()
    goal_period = (data.get("goal_period") or "day").strip()

    if goal_period not in {"day", "week", "month"}:
        goal_period = "day"

    goal_value = parse_float(goal_value_raw, None)
    if goal_value is None:
        goal_value = parse_float((data.get("target") or "").strip(), None)

    if goal_value is None:
        goal_value = 1

    if goal_value <= 0:
        return render_template("addhabits.html", error="Goal must be > 0", form=data)

    goal_doc = {
        "value": goal_value,
        "unit": goal_unit,
        "period": goal_period
    }

    habit_type = (data.get("type") or "binary").strip()
    unit_legacy = (data.get("unit") or "").strip()
    target_legacy = parse_float((data.get("target") or "").strip(), None)

    if not name:
        return render_template("addhabits.html", error="Name is required", form=data)

    if habit_type not in {"binary", "count"}:
        habit_type = "binary"

    if habit_type == "count":
        if not unit_legacy:
            return render_template("addhabits.html", error="Unit required for count", form=data)
        if target_legacy is None:
            return render_template("addhabits.html", error="Target required for count", form=data)
        if target_legacy <= 0:
            return render_template("addhabits.html", error="Target must be > 0", form=data)

    new_habit = {
        "userId": user_id,
        "name": name,

        "schedule": schedule_doc,
        "goal": goal_doc,

        "frequency": schedule_type,
        "type": habit_type,
        "category": category if category else None,
        "notes": notes if notes else None,
        "unit": unit_legacy if habit_type == "count" else None,
        "target": target_legacy if habit_type == "count" else None,

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
    ''' 
    Checkbox for done today or not done today
    '''
    user_id = str(current_user.id)
    today_str = today_str_local()

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
    '''
    routes to the view habits page
    '''
    user_id = str(current_user.id)

    habits = list(habit_collections.find({
        "userId": user_id,
        "archived": {"$ne": True}
    }))

    for h in habits:
        h["_id"] = str(h["_id"])

        if "schedule" not in h:
            h["schedule"] = {"type": h.get("frequency", "daily"), "start_date": today_str_local()}
        if "goal" not in h:
            if h.get("type") == "count" and h.get("target") is not None:
                h["goal"] = {"value": h.get("target"), "unit": h.get("unit") or "times", "period": "day"}
            else:
                h["goal"] = {"value": 1, "unit": "times", "period": "day"}

    return render_template("habits.html", habits=habits)


@dashboard_bp.route("/edithabit/<habit_id>", methods=["GET", "POST"])
@login_required
def edit_habit(habit_id):
    '''
    Allows the user to edit their habits
    '''
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

        schedule_type = (data.get("schedule_type") or (habit.get("schedule") or {}).get("type") or "daily").strip()
        custom_days_raw = data.getlist("custom_days")
        custom_days = [d for d in (parse_int(x, None) for x in custom_days_raw) if d is not None]

        if schedule_type not in {"daily", "weekly", "biweekly", "monthly", "custom"}:
            schedule_type = "daily"

        schedule_doc = habit.get("schedule") or {}
        schedule_doc["type"] = schedule_type
        schedule_doc.setdefault("start_date", today_str_local())

        if schedule_type == "custom":
            schedule_doc["custom_days"] = sorted(list(set(custom_days)))
        else:
            schedule_doc.pop("custom_days", None)

        goal_value_raw = (data.get("goal_value") or "").strip()
        goal_unit = (data.get("goal_unit") or "times").strip()
        goal_period = (data.get("goal_period") or "day").strip()

        if goal_period not in {"day", "week", "month"}:
            goal_period = "day"

        goal_value = parse_float(goal_value_raw, None)
        if goal_value is None:
            goal_value = parse_float((data.get("target") or "").strip(), None)
        if goal_value is None:
            goal_value = 1
        if goal_value <= 0:
            habit["_id"] = str(habit["_id"])
            habit["type"] = habit.get("type", "binary")
            return render_template("edithabit.html", habit=habit, error="Goal must be > 0")

        goal_doc = {"value": goal_value, "unit": goal_unit, "period": goal_period}

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
                return render_template("edithabit.html", habit=habit, error="Unit required for count")
            if not target_raw:
                habit["_id"] = str(habit["_id"])
                habit["type"] = habit.get("type", "binary")
                return render_template("edithabit.html", habit=habit, error="Target required for count")
            try:
                target = float(target_raw)
            except ValueError:
                habit["_id"] = str(habit["_id"])
                habit["type"] = habit.get("type", "binary")
                return render_template("edithabit.html", habit=habit, error="Target must be a number")
            if target <= 0:
                habit["_id"] = str(habit["_id"])
                habit["type"] = habit.get("type", "binary")
                return render_template("edithabit.html", habit=habit, error="Target must be > 0")

        set_fields = {
            "name": name,
            "type": habit_type,
            "schedule": schedule_doc,
            "goal": goal_doc,
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

    if "schedule" not in habit:
        habit["schedule"] = {"type": habit.get("frequency", "daily"), "start_date": today_str_local()}
    if "goal" not in habit:
        habit["goal"] = {"value": 1, "unit": "times", "period": "day"}

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
    query = (request.args.get("q") or "").strip()

    mongo_query = {
        "userId": user_id,
        "archived": {"$ne": True}
    }

    if query:
        mongo_query["name"] = {"$regex": query, "$options": "i"}

    habits = list(habit_collections.find(mongo_query))

    for h in habits:
        h["_id"] = str(h["_id"])

    return render_template("habits.html", habits=habits)


def calculate_streak(habit_id, user_id):
    ''' 
    Calculates daily streaks from users who do their habits
    '''
    today = datetime.now(ZoneInfo("America/New_York")).date()
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

@dashboard_bp.route("/profile")
@login_required
def profile():
    '''
    Allows Us to get the profile page
    '''
    user_id = str(current_user.id)

    user = None
    try:
        user = users_collection.find_one({"_id": ObjectId(user_id)})
    except (InvalidId, TypeError):
        user = None

    if not user:
        user = users_collection.find_one({"userId": user_id}) or users_collection.find_one({"_id": user_id})

    member_since = "N/A"
    if user:
        created = user.get("createdAt") or user.get("created_at") or user.get("created")
        if created:
            try:
                member_since = created.strftime("%Y-%m-%d")
            except Exception:
                member_since = str(created)

    habits = list(habit_collections.find({"userId": user_id, "archived": {"$ne": True}}))
    for h in habits:
        h["_id"] = str(h["_id"])
        h["streak"] = calculate_streak(h["_id"], user_id)
        h["completion_count"] = completions_collection.count_documents({"userId": user_id, "habitId": h["_id"]})

    total_habits = len(habits)
    total_completions = completions_collection.count_documents({"userId": user_id})
    best_streak = max([h["streak"] for h in habits], default=0)

    return render_template(
        "profile.html",
        user=user,
        member_since=member_since,
        habits=habits,
        total_habits=total_habits,
        total_completions=total_completions,
        best_streak=best_streak
    )

@dashboard_bp.route("/search")
@login_required
def search_page():
    """
    Search Page
    """
    return render_template("search.html")