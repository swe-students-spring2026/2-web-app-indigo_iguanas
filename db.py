"""
Database Setup for Microhabit
"""

import os
import datetime 

import pymongo
from dotenv import load_dotenv

# loading .env from same folder as the file
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

mongoURI = os.getenv('MONGO_URI')
DbName = os.getenv('MONGO_DBNAME')

if not mongoURI or not DbName:
    raise RuntimeError("Missing URI or DBName")

client = pymongo.MongoClient(mongoURI)
db = client[DbName]

users = db['users']
habits = db['habits']

client.admin.command('ping')  # Check if the connection is successful



if __name__ == "__main__":

    user = users.insert_one({
        'username': "test_user",
        'email': "test_user@nyu.edu",
        'password': "hashed_password"
    })

    userID = user.inserted_id

    habit = habits.insert_one({
        'user_id': userID,
        'name': "Test Habit",
        'description': "This is a test habit.",
        'frequency': "Daily",
        'created_at': datetime.datetime.now(),
    })

    print("Inserted User ID: ", userID)
    print("Inserted Habit ID: ", habit.inserted_id)
    