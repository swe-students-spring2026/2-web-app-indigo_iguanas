'''
Dashboard blueprints and routes for the Web App: Microhabit
'''

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bson.errors import InvalidId
from bson.objectid import ObjectId
from dotenv import load_dotenv
from flask import Blueprint, render_template, redirect, url_for, request
from flask_login import login_required, current_user
from pymongo import MongoClient

load_dotenv()

dashboard_bp = Blueprint("dashboard", __name__)


def today_str_local():
    '''
    This is to use local dates for the streaks to match their expectations
    '''
    return datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")


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
    schedule_type = (schedule.get("type") or habit.get("frequency") or "daily").strip().lower()

    if schedule_type == "daily":
        return True

    if schedule_type == "custom":
        custom_days = schedule.get("custom_days") or []
        if not custom_days:
            return True

        custom_days_int = []
        for value in custom_days:
            try:
                custom_days_int.append(int(value))
            except (TypeError, ValueError):
                continue

        if not custom_days_int:
            return True

        return today_dt.weekday() in set(custom_days_int)

    start_date = None
    start_str = schedule.get("start_date") or habit.get("createdOn")

    if start_str:
        try:
            start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
        except Exception:
            start_date = None

    if not start_date:
        created = habit.get("createdAt")
        if created and hasattr(created, "date"):
            start_date = created.date()

    if not start_date:
        start_date = today_dt

    if schedule_type in {"weekly", "biweekly"}:
        interval = 7 if schedule_type == "weekly" else 14
        delta = (today_dt - start_date).days
        return delta >= 0 and (delta % interval == 0)

    if schedule_type == "monthly":
        target_day = start_date.day
        next_month = (today_dt.replace(day=28) + timedelta(days=4)).replace(day=1)
        last_day_of_month = (next_month - timedelta(days=1)).day
        effective_day = min(target_day, last_day_of_month)
        return today_dt.day == effective_day

    return True



@dashboard_bp.route("/dashboard")
@login_required
def dashboard():
    user_id = str(current_user.id)
    today_str = today_str_local()
    today_dt = datetime.now(ZoneInfo("America/New_York")).date()

    habits = list(habit_collections.find({
        "userId": user_id,
        "archived": {"$ne": True}
    }).sort("createdAt", -1))

    due_habits = []
    for habit in habits:
        habit["_id"] = str(habit["_id"])

        if not should_show_today(habit, today_dt):
            continue

        window_status = get_current_window_status(habit["_id"], user_id)
        habit["window_start"] = window_status.get("start")
        habit["window_end"] = window_status.get("end")
        habit["window_completed"] = window_status.get("completed", 0)
        habit["window_required"] = window_status.get("required", 1)
        habit["completed_today"] = habit["window_completed"] >= habit["window_required"]
        habit["streak"] = calculate_streak(habit["_id"], user_id)

        due_habits.append(habit)

        if len(due_habits) >= 3:
            break

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

        "createdOn": today_str_local(),
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
    Marks habit completion for today.
    - For target > 1, each click increments completion count for today.
    - For target == 1, behaves as toggle for backward compatibility.
    - Optional action=decrement removes one completion for today.
    '''
    user_id = str(current_user.id)
    today_str = today_str_local()
    action = (request.form.get("action") or "increment").strip().lower()

    next_url = (request.form.get("next") or request.args.get("next") or "").strip()
    if not next_url.startswith("/"):
        next_url = ""

    try:
        habit = habit_collections.find_one({"_id": ObjectId(habit_id), "userId": user_id})
    except Exception:
        habit = None

    if not habit:
        return redirect(next_url or url_for("dashboard.dashboard"))

    required = 1
    goal = habit.get("goal") or {}
    try:
        required = int(float(goal.get("value", 1)))
    except (TypeError, ValueError):
        required = 1
    if required < 1:
        required = 1

    next_url = (request.form.get("next") or request.args.get("next") or "").strip()
    if not next_url.startswith("/"):
        next_url = ""

    if action == "decrement":
        if completion:
            completions_collection.delete_one({"_id": completion["_id"]})
    else:
        if required == 1:
            if completion:
                completions_collection.delete_one({"_id": completion["_id"]})
            else:
                completions_collection.insert_one({
                    "habitId": habit_id,
                    "userId": user_id,
                    "date": today_str
                })
        else:
            completions_collection.insert_one({
                "habitId": habit_id,
                "userId": user_id,
                "date": today_str
            })

    return redirect(next_url or url_for("dashboard.dashboard"))


@dashboard_bp.route("/viewhabits", methods=["GET"])
@login_required
def create_habit_get():
    '''
    routes to the view habits page
    '''
    user_id = str(current_user.id)
    today_str = today_str_local()

    habits = list(
        habit_collections.find(
            {
                "userId": user_id,
                "archived": {"$ne": True},
            }
        )
    )

    for h in habits:
        h["_id"] = str(h["_id"])

        if "schedule" not in h:
            h["schedule"] = {"type": h.get("frequency", "daily"), "start_date": today_str_local()}
        if "goal" not in h:
            if h.get("type") == "count" and h.get("target") is not None:
                h["goal"] = {"value": h.get("target"), "unit": h.get("unit") or "times", "period": "day"}
            else:
                h["goal"] = {"value": 1, "unit": "times", "period": "day"}

        h["completed_today_count"] = completions_collection.count_documents({
            "habitId": h["_id"],
            "userId": user_id,
            "date": today_str
        })

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
            "frequency": schedule_type,
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

    completions_collection.delete_many(
        {
            "habitId": habit_id,
            "userId": user_id,
        }
    )

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
        "archived": {"$ne": True},
    }

    if query:
        mongo_query["name"] = {"$regex": query, "$options": "i"}

    habits = list(habit_collections.find(mongo_query))

    for h in habits:
        h["_id"] = str(h["_id"])

    return render_template("habits.html", habits=habits)


def get_current_window_status(habit_id, user_id):
    def get_window_bounds(baseline, period):
        if period == "week":
            start = baseline - timedelta(days=baseline.weekday())
            end = start + timedelta(days=6)
            return start, end

        if period == "month":
            start = baseline.replace(day=1)
            if start.month == 12:
                next_month_start = start.replace(year=start.year + 1, month=1, day=1)
            else:
                next_month_start = start.replace(month=start.month + 1, day=1)
            end = next_month_start - timedelta(days=1)
            return start, end

        start = baseline
        end = baseline
        return start, end

    habit = None
    try:
        habit = habit_collections.find_one({"_id": ObjectId(habit_id), "userId": user_id})
    except Exception:
        habit = None

    if not habit:
        return {
            "start": None,
            "end": None,
            "completed": 0,
            "required": 1
        }

    goal = habit.get("goal") or {}
    period = (goal.get("period") or "day").strip().lower()
    if period not in {"day", "week", "month"}:
        period = "day"

    required_raw = goal.get("value", 1)
    try:
        required = int(float(required_raw))
    except (TypeError, ValueError):
        required = 1
    if required < 1:
        required = 1

    today = datetime.now(ZoneInfo("America/New_York")).date()
    window_start, window_end = get_window_bounds(today, period)

    completed = completions_collection.count_documents({
        "habitId": habit_id,
        "userId": user_id,
        "date": {
            "$gte": window_start.strftime("%Y-%m-%d"),
            "$lte": window_end.strftime("%Y-%m-%d")
        }
    })

    return {
        "start": window_start.strftime("%Y-%m-%d"),
        "end": window_end.strftime("%Y-%m-%d"),
        "completed": completed,
        "required": required
    }


def calculate_streak(habit_id, user_id):

    def get_window_bounds(baseline, period):
        if period == "week":
            start = baseline - timedelta(days=baseline.weekday())
            end = start + timedelta(days=6)
            return start, end

        if period == "month":
            start = baseline.replace(day=1)
            if start.month == 12:
                next_month_start = start.replace(year=start.year + 1, month=1, day=1)
            else:
                next_month_start = start.replace(month=start.month + 1, day=1)
            end = next_month_start - timedelta(days=1)
            return start, end

        start = baseline
        end = baseline
        return start, end

    def prev_window(window_start):
        return window_start - timedelta(days=1)

    habit = None

    try:
        habit = habit_collections.find_one({"_id": ObjectId(habit_id), "userId": user_id})
    except Exception:
        habit = None

    if not habit:
        return 0

    goal = habit.get("goal") or {}
    period = (goal.get("period") or "day").strip().lower()

    if period not in {"day", "week", "month"}:
        period = "day"

    required_raw = goal.get("value", 1)

    try:
        required = int(float(required_raw))
    except (TypeError, ValueError):
        required = 1
    if required < 1:
        required = 1

    today = datetime.now(ZoneInfo("America/New_York")).date()
    streak = 0

    current_start, current_end = get_window_bounds(today, period)

    current_count = completions_collection.count_documents({
        "habitId": habit_id,
        "userId": user_id,
        "date": {
            "$gte": current_start.strftime("%Y-%m-%d"),
            "$lte": current_end.strftime("%Y-%m-%d")
        }
    })

    if current_count >= required:
        streak += 1
        anchor = prev_window(current_start)
    else:
        anchor = prev_window(current_start)

    max_windows = 365
    windows_checked = 0

    while windows_checked < max_windows:
        window_start, window_end = get_window_bounds(anchor, period)
        
        count = completions_collection.count_documents({
            "habitId": habit_id,
            "userId": user_id,
            "date": {
                "$gte": window_start.strftime("%Y-%m-%d"),
                "$lte": window_end.strftime("%Y-%m-%d")
            }
        })

        if count >= required:
            streak += 1
            anchor = prev_window(window_start)
            windows_checked += 1
            continue

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
        user = (
            users_collection.find_one({"userId": user_id})
            or users_collection.find_one({"_id": user_id})
        )

    member_since = "N/A"
    if user:
        created = user.get("createdAt") or user.get("created_at") or user.get("created")
        if created:
            try:
                member_since = created.strftime("%Y-%m-%d")
            except (AttributeError, TypeError, ValueError):
                member_since = str(created)

    habits = list(
        habit_collections.find(
            {
                "userId": user_id,
                "archived": {"$ne": True},
            }
        )
    )
    for h in habits:
        h["_id"] = str(h["_id"])
        h["streak"] = calculate_streak(h["_id"], user_id)
        h["completion_count"] = completions_collection.count_documents(
            {
                "userId": user_id,
                "habitId": h["_id"],
            }
        )

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
        best_streak=best_streak,
    )


@dashboard_bp.route("/search")
@login_required
def search_page():
    """
    Search Page
    """
    return render_template("search.html")