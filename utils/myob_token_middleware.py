
import requests
from datetime import datetime, timedelta
from functools import wraps
from config import Config
from utils.mongodb import MongoDB


def refresh_myob_token(connection):
    """
    Refresh MYOB access token using refresh_token
    """
    response = requests.post(
        Config.MYOB_BUSINESS_TOKEN_URL,
        headers={
            "Content-Type": "application/x-www-form-urlencoded"
        },
        data={
            "client_id": Config.MYOB_CLIENT_ID,
            "client_secret": Config.MYOB_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": connection["refresh_token"],
        },
        timeout=20
    )

    if response.status_code != 200:
        raise Exception(f"MYOB token refresh failed: {response.text}")

    token_data = response.json()

    # Ensure expires_in is an integer to avoid TypeError in timedelta
    try:
        expires_in = int(token_data.get("expires_in", 1200))
    except (ValueError, TypeError):
        expires_in = 1200

    expires_at = datetime.now() + timedelta(seconds=expires_in)

    MongoDB.get_collection("myob_connections").update_one(
        {"_id": connection["_id"]},
        {"$set": {
            "access_token": token_data["access_token"],
            "refresh_token": token_data.get("refresh_token", connection["refresh_token"]),
            "token_expires_at": expires_at,
            "updated_at": datetime.now()
        }}
    )

    return token_data["access_token"]


def get_valid_myob_token(user_id, api_type="business"):
    """
    Get valid MYOB token, refreshing if expired
    Returns: (access_token, business_id)
    """
    connection = MongoDB.get_collection("myob_connections").find_one({
        "user_id": user_id,
        "connection_status": "connected",
        "api_type": api_type
    })

    if not connection:
        raise Exception("MYOB not connected. Please connect to MYOB first.")

    # Check if token is expired
    if connection.get("token_expires_at") and connection.get("token_expires_at") <= datetime.now():
        # Refresh the token
        new_token = refresh_myob_token(connection)
        connection["access_token"] = new_token

    return connection["access_token"], connection.get("business_id")


def myob_token_required(api_type="business"):
    """
    Decorator to auto refresh MYOB token if expired
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):

            user_id = kwargs.get("user_id")

            connection = MongoDB.get_collection("myob_connections").find_one({
                "user_id": user_id,
                "connection_status": "connected",
                "api_type": api_type
            })

            if not connection:
                raise Exception("MYOB not connected")

            # 🔥 Token expired?
            if connection.get("token_expires_at") and connection.get("token_expires_at") <= datetime.now():
                new_token = refresh_myob_token(connection)
                connection["access_token"] = new_token

            kwargs["myob_access_token"] = connection["access_token"]
            kwargs["business_id"] = connection.get("business_id")

            return func(*args, **kwargs)

        return wrapper
    return decorator
