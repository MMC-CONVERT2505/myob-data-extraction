# import os
# from dotenv import load_dotenv

# load_dotenv()

# class Config:
#     # Flask Configuration
#     SECRET_KEY = os.getenv('SECRET_KEY', 'myob-super-secret-fixed-key-123')
#     SESSION_TYPE = 'filesystem'
    
#     # MongoDB Configuration
#     MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
#     MONGO_DB = os.getenv('MONGO_DB', 'myob_extractor')
    
#     # MYOB Business API Configuration
#     MYOB_CLIENT_ID = os.getenv('MYOB_CLIENT_ID', '19c4e50c-21ee-4cd9-8b6c-f5487cdd7842')
#     MYOB_CLIENT_SECRET = os.getenv('MYOB_CLIENT_SECRET', 'WM8U1DIeAsD6v6q22vFZLanR')
#     MYOB_REDIRECT_URI = os.getenv('MYOB_REDIRECT_URI', 'http://localhost:5001/myob_auth_code')
#     MYOB_API_BASE_URL = 'https://api.myob.com/accountright/{businessId}/'
#     MYOB_AUTH_URL = 'https://secure.myob.com/oauth2/account/authorize'
#     MYOB_TOKEN_URL = 'https://secure.myob.com/oauth2/v1/authorize'
#     MYOB_BUSINESS_TOKEN_URL = 'https://secure.myob.com/oauth2/v1/authorize'
#     MYOB_SCOPES = 'sme-company-settings sme-sales' #'sme-company-file sme-invoi ce'
    
#     # Email Configuration
#     MAIL_SERVER = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
#     MAIL_PORT = int(os.getenv('MAIL_PORT', 587))
#     MAIL_USE_TLS = os.getenv('MAIL_USE_TLS', 'True') == 'True'
#     MAIL_USERNAME = os.getenv('MAIL_USERNAME', '')
#     MAIL_PASSWORD = os.getenv('MAIL_PASSWORD', '')
#     MAIL_DEFAULT_SENDER = os.getenv('MAIL_DEFAULT_SENDER', 'noreply@myob-extractor.com')
    
#     # Password Reset
#     PASSWORD_RESET_EXPIRY = int(os.getenv('PASSWORD_RESET_EXPIRY', 3600))
    
#     # Application Settings
#     UPLOAD_FOLDER = 'static/uploads'
    
#     # API Limits
#     MYOB_RATE_LIMIT_REQUESTS = 100
#     MYOB_RATE_LIMIT_PERIOD = 300
#     MYOB_MAX_RETRIES = 3
#     MYOB_RETRY_DELAY = 2

import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Flask Configuration
    SECRET_KEY = os.getenv('SECRET_KEY', 'myob-super-secret-fixed-key-123')
    SESSION_TYPE = 'filesystem'
    
    # MongoDB Configuration
    MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
    MONGO_DB = os.getenv('MONGO_DB', 'myob_extractor')
    
    # MYOB Business API Configuration
    MYOB_CLIENT_ID = os.getenv('MYOB_CLIENT_ID', '19c4e50c-21ee-4cd9-8b6c-f5487cdd7842')
    MYOB_CLIENT_SECRET = os.getenv('MYOB_CLIENT_SECRET', 'WM8U1DIeAsD6v6q22vFZLanR')
    # MYOB_REDIRECT_URI = os.getenv('MYOB_REDIRECT_URI', 'http://localhost:5001/myob_auth_code')
    MYOB_REDIRECT_URI = os.getenv('MYOB_REDIRECT_URI', 'http://3.236.240.156/myob/callback')
    MYOB_API_BASE_URL = 'https://api.myob.com/accountright/{businessId}/'
    MYOB_AUTH_URL = 'https://secure.myob.com/oauth2/account/authorize'
    MYOB_TOKEN_URL = 'https://secure.myob.com/oauth2/v1/authorize'
    MYOB_BUSINESS_TOKEN_URL = 'https://secure.myob.com/oauth2/v1/authorize'
    MYOB_SCOPES = 'sme-company-settings sme-sales sme-purchases sme-contacts-customer sme-contacts-supplier sme-company-file'
    
     
    # Email Configuration
    MAIL_SERVER = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.getenv('MAIL_PORT', 587))
    MAIL_USE_TLS = os.getenv('MAIL_USE_TLS', 'True') == 'True'
    MAIL_USERNAME = os.getenv('MAIL_USERNAME', '')
    MAIL_PASSWORD = os.getenv('MAIL_PASSWORD', '')
    MAIL_DEFAULT_SENDER = os.getenv('MAIL_DEFAULT_SENDER', 'noreply@myob-extractor.com')
    
    # Password Reset
    PASSWORD_RESET_EXPIRY = int(os.getenv('PASSWORD_RESET_EXPIRY', 3600))
    
    # Application Settings
    UPLOAD_FOLDER = 'static/uploads'
    
    # API Limits
    MYOB_RATE_LIMIT_REQUESTS = 100
    MYOB_RATE_LIMIT_PERIOD = 300
    MYOB_MAX_RETRIES = 3
    MYOB_RETRY_DELAY = 2

    