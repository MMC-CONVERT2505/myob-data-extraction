
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import ConnectionFailure
from config import Config
import bcrypt
from datetime import datetime , timedelta
import logging

logger = logging.getLogger(__name__)

class MongoDB:
    _client = None
    _db = None
    
    @classmethod
    def get_client(cls):
        if cls._client is None:
            try:
                cls._client = MongoClient(Config.MONGO_URI)
                # Test connection
                cls._client.admin.command('ping')
                logger.info("Connected to MongoDB successfully")
            except ConnectionFailure as e:
                logger.error(f"Failed to connect to MongoDB: {e}")
                raise
        return cls._client
    
    @classmethod
    def get_database(cls):
        if cls._db is None:
            client = cls.get_client()
            cls._db = client[Config.MONGO_DB]
        return cls._db
    
    @classmethod
    def get_collection(cls, collection_name):
        db = cls.get_database()
        return db[collection_name]
    
    @classmethod
    def init_database(cls):
        """Initialize database with collections and indexes"""
        try:
            db = cls.get_database()
            
            # Users collection
            users = db['users']
            users.create_index([('email', ASCENDING)], unique=True)
            users.create_index([('created_at', DESCENDING)])
            
            # MYOB Connections collection
            connections = db['myob_connections']
            connections.create_index([('user_id', ASCENDING)])
            connections.create_index([('connection_status', ASCENDING)])
            connections.create_index([('created_at', DESCENDING)])
            
            # Extraction History collection
            history = db['extraction_history']
            history.create_index([('user_id', ASCENDING)])
            history.create_index([('created_at', DESCENDING)])
            history.create_index([('extraction_type', ASCENDING)])
            
            # User Sessions collection
            sessions = db['user_sessions']
            sessions.create_index([('user_id', ASCENDING)])
            sessions.create_index([('expires_at', DESCENDING)])
            sessions.create_index([('created_at', DESCENDING)])
            
            # OAuth States collection
            oauth_states = db['oauth_states']
            oauth_states.create_index([('state', ASCENDING)], unique=True)
            oauth_states.create_index([('user_id', ASCENDING)])
            oauth_states.create_index([('expires_at', DESCENDING)])

            # Create default admin user if not exists
            cls.create_default_users()
            
            logger.info("MongoDB initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error initializing MongoDB: {e}")
            return False
    
    @classmethod
    def create_default_users(cls):
        """Create default admin and test users"""
        try:
            users = cls.get_collection('users')
            
            # Admin user (password: Admin@123)
            admin_password = bcrypt.hashpw('Admin@123'.encode('utf-8'), bcrypt.gensalt())
            users.update_one(
                {'email': 'admin@myob.com'},
                {'$set': {
                    'full_name': 'Admin User',
                    'email': 'admin@myob.com',
                    'password_hash': admin_password,
                    'role': 'admin',
                    'company_name': 'Admin Company',
                    'is_active': True,
                    'created_at': datetime.now(),
                    'updated_at': datetime.now()
                }},
                upsert=True
            )
            
            # Test user (password: Test@123)
            test_password = bcrypt.hashpw('Test@123'.encode('utf-8'), bcrypt.gensalt())
            users.update_one(
                {'email': 'test@myob.com'},
                {'$set': {
                    'full_name': 'Test User',
                    'email': 'test@myob.com',
                    'password_hash': test_password,
                    'role': 'user',
                    'company_name': 'Test Company',
                    'is_active': True,
                    'created_at': datetime.now(),
                    'updated_at': datetime.now()
                }},
                upsert=True
            )
            
            logger.info("Default users created")
            
        except Exception as e:
            logger.error(f"Error creating default users: {e}")

    @classmethod
    def save_user_session(cls, user_id, session_data):
        """Save user session data to MongoDB"""
        try:
            sessions = cls.get_collection('user_sessions')
            
            # Prepare session data
            session_record = {
                'user_id': user_id,
                'session_data': session_data,
                'created_at': datetime.now(),
                'updated_at': datetime.now(),
                'expires_at': datetime.now() + timedelta(hours=24)
            }
            
            # Update or insert
            sessions.update_one(
                {'user_id': user_id},
                {'$set': session_record},
                upsert=True
            )
            
            logger.debug(f"Session saved for user: {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error saving session: {e}")
            return False
    
    @classmethod
    def get_user_session(cls, user_id):
        """Get user session data from MongoDB"""
        try:
            sessions = cls.get_collection('user_sessions')
            session_data = sessions.find_one({
                'user_id': user_id,
                'expires_at': {'$gt': datetime.now()}
            })
            
            if session_data:
                logger.debug(f"Session found for user: {user_id}")
                return session_data.get('session_data', {})
            else:
                logger.debug(f"No active session for user: {user_id}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting session: {e}")
            return None
    
    @classmethod
    def delete_user_session(cls, user_id):
        """Delete user session"""
        try:
            sessions = cls.get_collection('user_sessions')
            result = sessions.delete_one({'user_id': user_id})
            
            logger.debug(f"Session deleted for user: {user_id}")
            return result.deleted_count > 0
            
        except Exception as e:
            logger.error(f"Error deleting session: {e}")
            return False
    
    @classmethod
    def save_oauth_state(cls, user_id, state):
        """Save OAuth state for later verification"""
        try:
            oauth_states = cls.get_collection('oauth_states')
            
            state_record = {
                'user_id': user_id,
                'state': state,
                'created_at': datetime.now(),
                'expires_at': datetime.now() + timedelta(minutes=30)
            }
            
            oauth_states.insert_one(state_record)
            logger.debug(f"OAuth state saved: {state} for user: {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error saving OAuth state: {e}")
            return False
    
    @classmethod
    def verify_oauth_state(cls, state):
        """Verify OAuth state exists and is not expired"""
        try:
            oauth_states = cls.get_collection('oauth_states')
            state_record = oauth_states.find_one({
                'state': state,
                'expires_at': {'$gt': datetime.now()}
            })
            
            if state_record:
                logger.debug(f"OAuth state verified: {state}")
                return state_record
            else:
                logger.debug(f"OAuth state not found or expired: {state}")
                return None
                
        except Exception as e:
            logger.error(f"Error verifying OAuth state: {e}")
            return None
    
    @classmethod
    def delete_oauth_state(cls, state):
        """Delete used OAuth state"""
        try:
            oauth_states = cls.get_collection('oauth_states')
            result = oauth_states.delete_one({'state': state})
            
            logger.debug(f"OAuth state deleted: {state}")
            return result.deleted_count > 0
            
        except Exception as e:
            logger.error(f"Error deleting OAuth state: {e}")
            return False

    

# Helper functions for MongoDB operations
def hash_password(password):
    """Hash password using bcrypt"""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

def verify_password(stored_hash, password):
    """Verify password using bcrypt"""
    if isinstance(stored_hash, str):
        stored_hash = stored_hash.encode('utf-8')
    return bcrypt.checkpw(password.encode('utf-8'), stored_hash)

def create_password_reset_token(email):
    """Create password reset token"""
    # Implementation for storing reset tokens in MongoDB
    pass