"""
Dashboard blueprints and routes for the Web App: Microhabit
"""

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bson.errors import InvalidId
from bson.objectid import ObjectId
from dotenv import load_dotenv
from flask import Blueprint, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from pymongo import MongoClient

load_dotenv()

dashboard_bp = Blueprint("dashboard", __name__)

NY_TZ = ZoneInfo("America/New_York")


def today_str_local():
    """
    Use local dates for streaks to match user expectations.
    """
    return datetime.now(NY_TZ).strftime("%Y-%m-%d")


mongo_client = MongoClient(os.getenv("MONGO_URI"))
database = mongo_client[os.getenv("MONGO_DBNAME")]
habits_collection = database["habits"]
completions_collection = database["completions"]
users_collection = database["users"]


def parse_int(value, default=None):
    """
    Safely convert a value to an integer.

    Args:
        value: Value to convert.
        default: Value returned if conversion fails.

    Returns:
        int | Any: Converted int or default.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_float(value, default=None):
    """
    Safely convert a value to a float.

    Args:
        value: Value to convert.
        default: Value returned if conversion fails.

    Returns:
        float | Any: Converted float or default.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def should_show_today(habit, today_date):
    """
    Determine whether a habit should be shown on a specific date.
    """
    schedule = habit.get("schedule") or {}
    schedule_type = (
        schedule.get("type")
        or habit.get("frequency")
        or "daily"
    ).strip().lower()

    if schedule_type == "daily":
        return True

    if schedule_type == "custom":
        custom_days = schedule.get("custom_days") or []
        if not custom_days:
            return True

        custom_days_int = []
        for day_value in custom_days:
            parsed = parse_int(day_value, None)
            if parsed is not None:
                custom_days_int.append(parsed)

        if not custom_days_int:
            return True

        return today_date.weekday() in set(custom_days_int)

    start_date = None
    start_str = schedule.get("start_date") or habit.get("createdOn")

    if start_str:
        try:
            start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
        except ValueError:
            start_date = None

    if not start_date:
        created_at = habit.get("createdAt")
        if created_at and hasattr(created_at, "date"):
            start_date = created_at.date()

    if not start_date:
        start_date = today_date

    if schedule_type in {"weekly", "biweekly"}:
        interval = 7 if schedule_type == "weekly" else 14
        delta_days = (today_date - start_date).days
        return delta_days >= 0 and (delta_days % interval == 0)

    if schedule_type == "monthly":
        target_day = start_date.day
        next_month = (today_date.replace(day=28) + timedelta(days=4)).replace(day=1)
        last_day_of_month = (next_month - timedelta(days=1)).day
        effective_day = min(target_day, last_day_of_month)
        return today_date.day == effective_day

    return True


@dashboard_bp.route("/dashboard")
@login_required
def dashboard():
    """
    Render the main dashboard for logged in users.
    """
    user_id = str(current_user.id)
    today_str = today_str_local()
    today_date = datetime.now(NY_TZ).date()

    habits = list(
        habits_collection.find(
            {
                "userId": user_id,
                "archived": {"$ne": True},
            }
        ).sort("createdAt", -1)
    )

    due_habits = []
    for habit in habits:
        habit["_id"] = str(habit["_id"])

        if not should_show_today(habit, today_date):
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

    done_habits = [habit for habit in due_habits if habit.get("completed_today")]
    not_done_habits = [habit for habit in due_habits if not habit.get("completed_today")]

    return render_template(
        "dashboard.html",
        habits=due_habits,
        done_habits=done_habits,
        not_done_habits=not_done_habits,
        today_str=today_str,
    )


@dashboard_bp.route("/habits/new", methods=["GET"])
@login_required
def add_habit_page():
    """
    Render the add habit page.
    """
    return render_template("addhabits.html")


@dashboard_bp.route("/habits", methods=["POST"])
@login_required
def create_habit():
    """
    Allow user to create habits.
    """
    data = request.form
    user_id = str(current_user.id)

    name = (data.get("name") or "").strip()
    category = (data.get("category") or "").strip()
    notes = (data.get("notes") or "").strip()

    schedule_type = (data.get("schedule_type") or "daily").strip().lower()
    custom_days_raw = data.getlist("custom_days")
    custom_days = [
        day
        for day in (parse_int(val, None) for val in custom_days_raw)
        if day is not None
    ]

    if schedule_type not in {"daily", "weekly", "biweekly", "monthly", "custom"}:
        schedule_type = "daily"

    if schedule_type == "custom" and not custom_days:
        custom_days = [0, 1, 2, 3, 4]

    schedule_doc = {"type": schedule_type, "start_date": today_str_local()}
    if schedule_type == "custom":
        schedule_doc["custom_days"] = sorted(set(custom_days))

    goal_value_raw = (data.get("goal_value") or "").strip()
    goal_unit = (data.get("goal_unit") or "times").strip()
    goal_period = (data.get("goal_period") or "day").strip().lower()

    if goal_period not in {"day", "week", "month"}:
        goal_period = "day"

    goal_value = parse_float(goal_value_raw, None)
    if goal_value is None:
        goal_value = parse_float((data.get("target") or "").strip(), None)
    if goal_value is None:
        goal_value = 1

    if goal_value <= 0:
        return render_template("addhabits.html", error="Goal must be > 0", form=data)

    goal_doc = {"value": goal_value, "unit": goal_unit, "period": goal_period}

    habit_type = (data.get("type") or "binary").strip().lower()
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

    new_habit = {key: value for key, value in new_habit.items() if value is not None}
    habits_collection.insert_one(new_habit)

    return redirect(url_for("dashboard.create_habit_get"))


@dashboard_bp.route("/toggle/<habit_id>", methods=["POST"])
@login_required
def toggle_habit(habit_id):
    """
    Marks habit completion for today.
    For goal value > 1, each click increments completion count for today.
    For goal value == 1, behaves as toggle for backward compatibility.
    Optional action=decrement removes one completion for today.
    """
    user_id = str(current_user.id)
    today_str = today_str_local()
    action = (request.form.get("action") or "increment").strip().lower()

    next_url = (request.form.get("next") or request.args.get("next") or "").strip()
    if not next_url.startswith("/"):
        next_url = ""

    try:
        habit = habits_collection.find_one(
            {"_id": ObjectId(habit_id), "userId": user_id}
        )
    except (InvalidId, TypeError):
        habit = None

    if not habit:
        return redirect(next_url or url_for("dashboard.dashboard"))

    goal = habit.get("goal") or {}
    required = parse_int(goal.get("value", 1), 1)
    if required is None or required < 1:
        required = 1

    completion = completions_collection.find_one(
        {
            "habitId": habit_id,
            "userId": user_id,
            "date": today_str,
        }
    )

    if action == "decrement":
        if completion:
            completions_collection.delete_one({"_id": completion["_id"]})
    else:
        if required == 1:
            if completion:
                completions_collection.delete_one({"_id": completion["_id"]})
            else:
                completions_collection.insert_one(
                    {"habitId": habit_id, "userId": user_id, "date": today_str}
                )
        else:
            completions_collection.insert_one(
                {"habitId": habit_id, "userId": user_id, "date": today_str}
            )

    return redirect(next_url or url_for("dashboard.dashboard"))


@dashboard_bp.route("/viewhabits", methods=["GET"])
@login_required
def create_habit_get():
    """
    Route to the view habits page.
    """
    user_id = str(current_user.id)
    today_str = today_str_local()

    habits = list(
        habits_collection.find(
            {
                "userId": user_id,
                "archived": {"$ne": True},
            }
        )
    )

    for habit in habits:
        habit["_id"] = str(habit["_id"])

        if "schedule" not in habit:
            habit["schedule"] = {
                "type": habit.get("frequency", "daily"),
                "start_date": today_str_local(),
            }

        if "goal" not in habit:
            if habit.get("type") == "count" and habit.get("target") is not None:
                habit["goal"] = {
                    "value": habit.get("target"),
                    "unit": habit.get("unit") or "times",
                    "period": "day",
                }
            else:
                habit["goal"] = {"value": 1, "unit": "times", "period": "day"}

        habit["completed_today_count"] = completions_collection.count_documents(
            {
                "habitId": habit["_id"],
                "userId": user_id,
                "date": today_str,
            }
        )

    return render_template("habits.html", habits=habits)


@dashboard_bp.route("/edithabit/<habit_id>", methods=["GET", "POST"])
@login_required
def edit_habit(habit_id):
    """
    Allow the user to edit their habits.
    """
    user_id = str(current_user.id)

    try:
        habit_object_id = ObjectId(habit_id)
    except InvalidId:
        return redirect(url_for("dashboard.create_habit_get"))

    habit = habits_collection.find_one(
        {"_id": habit_object_id, "userId": user_id}
    )
    if not habit:
        return redirect(url_for("dashboard.create_habit_get"))

    if request.method == "POST":
        data = request.form

        name = (data.get("name") or "").strip()
        category = (data.get("category") or "").strip()
        notes = (data.get("notes") or "").strip()

        schedule_type = (
            data.get("schedule_type")
            or (habit.get("schedule") or {}).get("type")
            or "daily"
        ).strip().lower()

        custom_days_raw = data.getlist("custom_days")
        custom_days = [
            day
            for day in (parse_int(val, None) for val in custom_days_raw)
            if day is not None
        ]

        if schedule_type not in {"daily", "weekly", "biweekly", "monthly", "custom"}:
            schedule_type = "daily"

        schedule_doc = habit.get("schedule") or {}
        schedule_doc["type"] = schedule_type
        schedule_doc.setdefault("start_date", today_str_local())

        if schedule_type == "custom":
            schedule_doc["custom_days"] = sorted(set(custom_days))
        else:
            schedule_doc.pop("custom_days", None)

        goal_value_raw = (data.get("goal_value") or "").strip()
        goal_unit = (data.get("goal_unit") or "times").strip()
        goal_period = (data.get("goal_period") or "day").strip().lower()

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

        habit_type = (data.get("type") or "binary").strip().lower()
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
                return render_template("edithabit.html",
                                        habit=habit,
                                        error="Unit required for count"
                                        )

            if not target_raw:
                habit["_id"] = str(habit["_id"])
                habit["type"] = habit.get("type", "binary")
                return render_template("edithabit.html",
                                        habit=habit,
                                        error="Target required for count"
                                        )

            target = parse_float(target_raw, None)
            if target is None:
                habit["_id"] = str(habit["_id"])
                habit["type"] = habit.get("type", "binary")
                return render_template("edithabit.html",
                                        habit=habit,
                                        error="Target must be a number"
                                        )

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

        habits_collection.update_one(
            {"_id": habit_object_id, "userId": user_id},
            update_doc,
        )
        return redirect(url_for("dashboard.create_habit_get"))

    habit["_id"] = str(habit["_id"])
    habit["type"] = habit.get("type", "binary")

    if "schedule" not in habit:
        habit["schedule"] = {
            "type": habit.get("frequency", "daily"),
            "start_date": today_str_local(),
        }
    if "goal" not in habit:
        habit["goal"] = {"value": 1, "unit": "times", "period": "day"}

    return render_template("edithabit.html", habit=habit)


@dashboard_bp.route("/habits/<habit_id>/delete", methods=["POST"])
@login_required
def delete_habit(habit_id):
    """
    Allow the user to delete their habits.
    """
    user_id = str(current_user.id)

    try:
        habit_object_id = ObjectId(habit_id)
    except InvalidId:
        return redirect(url_for("dashboard.dashboard"))

    habits_collection.delete_one({"_id": habit_object_id, "userId": user_id})

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
    Allow the user to search for their habits.
    """
    user_id = str(current_user.id)
    query = (request.args.get("q") or "").strip()
    today_str = today_str_local()

    mongo_query = {
        "userId": user_id,
        "archived": {"$ne": True},
    }

    if query:
        mongo_query["name"] = {"$regex": query, "$options": "i"}

    habits = list(habits_collection.find(mongo_query))

    for habit in habits:
        habit["_id"] = str(habit["_id"])

        if "schedule" not in habit:
            habit["schedule"] = {
                "type": habit.get("frequency", "daily"),
                "start_date": today_str_local(),
            }

        if "goal" not in habit:
            if habit.get("type") == "count" and habit.get("target") is not None:
                habit["goal"] = {
                    "value": habit.get("target"),
                    "unit": habit.get("unit") or "times",
                    "period": "day",
                }
            else:
                habit["goal"] = {"value": 1, "unit": "times", "period": "day"}

        habit["completed_today_count"] = completions_collection.count_documents(
            {
                "habitId": habit["_id"],
                "userId": user_id,
                "date": today_str,
            }
        )

    return render_template("habits.html", habits=habits)


def get_current_window_status(habit_id, user_id):
    """
    Compute the current goal window and the user's completion count in that window.
    """
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

        return baseline, baseline

    try:
        habit = habits_collection.find_one(
            {"_id": ObjectId(habit_id), "userId": user_id}
        )
    except (InvalidId, TypeError):
        habit = None

    if not habit:
        return {"start": None, "end": None, "completed": 0, "required": 1}

    goal = habit.get("goal") or {}
    period = (goal.get("period") or "day").strip().lower()
    if period not in {"day", "week", "month"}:
        period = "day"

    required = parse_int(goal.get("value", 1), 1)
    if required is None or required < 1:
        required = 1

    today_date = datetime.now(NY_TZ).date()
    window_start, window_end = get_window_bounds(today_date, period)

    completed = completions_collection.count_documents(
        {
            "habitId": habit_id,
            "userId": user_id,
            "date": {
                "$gte": window_start.strftime("%Y-%m-%d"),
                "$lte": window_end.strftime("%Y-%m-%d"),
            },
        }
    )

    return {
        "start": window_start.strftime("%Y-%m-%d"),
        "end": window_end.strftime("%Y-%m-%d"),
        "completed": completed,
        "required": required,
    }


def calculate_streak(habit_id, user_id):
    """
    Calculate the current streak for a habit based on its goal period and required completions.
    """
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

        return baseline, baseline

    def prev_window(window_start):
        return window_start - timedelta(days=1)

    try:
        habit = habits_collection.find_one({"_id": ObjectId(habit_id), "userId": user_id})
    except (InvalidId, TypeError):
        habit = None

    if not habit:
        return 0

    goal = habit.get("goal") or {}
    period = (goal.get("period") or "day").strip().lower()
    if period not in {"day", "week", "month"}:
        period = "day"

    required = parse_int(goal.get("value", 1), 1)
    if required is None or required < 1:
        required = 1

    today_date = datetime.now(NY_TZ).date()
    streak = 0

    current_start, current_end = get_window_bounds(today_date, period)

    current_count = completions_collection.count_documents(
        {
            "habitId": habit_id,
            "userId": user_id,
            "date": {
                "$gte": current_start.strftime("%Y-%m-%d"),
                "$lte": current_end.strftime("%Y-%m-%d"),
            },
        }
    )

    if current_count >= required:
        streak += 1

    anchor = prev_window(current_start)

    max_windows = 365
    windows_checked = 0

    while windows_checked < max_windows:
        window_start, window_end = get_window_bounds(anchor, period)

        window_completion_count = completions_collection.count_documents(
            {
                "habitId": habit_id,
                "userId": user_id,
                "date": {
                    "$gte": window_start.strftime("%Y-%m-%d"),
                    "$lte": window_end.strftime("%Y-%m-%d"),
                },
            }
        )

        if window_completion_count >= required:
            streak += 1
            anchor = prev_window(window_start)
            windows_checked += 1
            continue

        break

    return streak


@dashboard_bp.route("/profile")
@login_required
def profile():
    """
    Render the profile page.
    """
    user_id = str(current_user.id)

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
        habits_collection.find(
            {
                "userId": user_id,
                "archived": {"$ne": True},
            }
        )
    )

    for habit in habits:
        habit["_id"] = str(habit["_id"])
        habit["streak"] = calculate_streak(habit["_id"], user_id)
        habit["completion_count"] = completions_collection.count_documents(
            {
                "userId": user_id,
                "habitId": habit["_id"],
            }
        )

    total_habits = len(habits)
    total_completions = completions_collection.count_documents({"userId": user_id})
    best_streak = max((habit["streak"] for habit in habits), default=0)

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
    Search page.
    """
    return render_template("search.html")
