import pymongo
from bson.objectid import ObjectId
import datetime

import os
from dotenv import load_dotenv

load_dotenv()

#remember to use 

mongo_uri = os.getenv("MONGO_URI")
db_name = os.getenv("MONGO_DBNAME")

client = MongoClient(mongo_uri)
db = client[db_name]

users_collection = db["users"]
habits_collection = db["habits"]
completions_collection = db["completions"]

test = True
if test: 

    user = users.insert_one({
        'username': "test_user",
        #"username", unique=True : for unique usernames
        'email': "test_user@nyu.edu"
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

