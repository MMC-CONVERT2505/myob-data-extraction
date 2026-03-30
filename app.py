

from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file
from flask_session import Session
from flask_cors import CORS
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer
from utils.myob_business_api import MYOBBusinessAPI
import os
import json
import uuid
from datetime import datetime, timedelta
import pandas as pd
import requests
from urllib.parse import urlencode
from functools import wraps
from bson import ObjectId
from config import Config
from utils.mongodb import MongoDB, hash_password, verify_password
from utils.converters import ConverterFactory
from utils.myob_token_middleware import myob_token_required
 


# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = Config.SECRET_KEY
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=1)
app.config['SESSION_COOKIE_NAME'] = 'myob_extractor_session'
app.config['SESSION_COOKIE_SECURE'] = False  # Development में False
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # Important for OAuth
app.config['SESSION_REFRESH_EACH_REQUEST'] = True


Session(app)
# Email configuration
app.config['MAIL_SERVER'] = Config.MAIL_SERVER
app.config['MAIL_PORT'] = Config.MAIL_PORT
app.config['MAIL_USE_TLS'] = Config.MAIL_USE_TLS
app.config['MAIL_USERNAME'] = Config.MAIL_USERNAME
app.config['MAIL_PASSWORD'] = Config.MAIL_PASSWORD
app.config['MAIL_DEFAULT_SENDER'] = Config.MAIL_DEFAULT_SENDER

mail = Mail(app)
CORS(app, supports_credentials=True, resources={r"/*": {"origins": ["http://3.236.240.156"]}})

# Password reset token serializer
serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])

# Create directories
os.makedirs('static/exports', exist_ok=True)

# ========================
# MONGODB INITIALIZATION
# ========================

def init_database():
    """Initialize MongoDB database"""
    try:
        # Just test the connection
        client = MongoDB.get_client()
        client.admin.command('ping')
        print("✅ MongoDB connected successfully")
        return True
    except Exception as e:
        print(f"❌ MongoDB connection failed: {e}")
        return False

# ========================
# AUTHENTICATION DECORATOR
# ========================

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            print(f"DEBUG: Redirecting to login. Session keys: {list(session.keys())}. URL requested: {request.url}")
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated_function

# ========================
# AUTHENTICATION ROUTES
# ========================

@app.route('/')
def home():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login_page'))

@app.route('/login')
def login_page():
    return render_template('login.html')

@app.route('/signup')
def signup_page():
    return render_template('signup.html')

@app.route('/api/login', methods=['POST'])
def login():
    try:
        data = request.json
        email = data.get('email')
        password = data.get('password')

        if not email or not password:
            return jsonify({'success': False, 'message': 'Email and password required'})

        # Check user in MongoDB
        users = MongoDB.get_collection('users')
        user = users.find_one({'email': email, 'is_active': True})

        if user and verify_password(user['password_hash'], password):
            # Update last login
            users.update_one(
                {'_id': user['_id']},
                {'$set': {'last_login': datetime.now()}}
            )

            # Set session
            session['user_id'] = str(user['_id'])
            session['user_email'] = user['email']
            session['user_name'] = user['full_name']
            session['user_role'] = user.get('role', 'user')
            session.permanent = True
            session.modified = True

            return jsonify({
                'success': True,
                'message': 'Login successful',
                'user': {
                    'id': str(user['_id']),
                    'name': user['full_name'],
                    'email': user['email'],
                    'role': user.get('role', 'user')
                }
            })
        else:
            return jsonify({'success': False, 'message': 'Invalid email or password'})

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/signup', methods=['POST'])
def signup():
    try:
        data = request.json
        full_name = data.get('full_name')
        email = data.get('email')
        password = data.get('password')
        company_name = data.get('company_name', '')

        if not full_name or not email or not password:
            return jsonify({'success': False, 'message': 'All fields are required'})

        # Check if user already exists
        users = MongoDB.get_collection('users')
        existing = users.find_one({'email': email})

        if existing:
            return jsonify({'success': False, 'message': 'Email already registered'})

        # Hash password
        password_hash = hash_password(password)

        # Create user document
        user_data = {
            'full_name': full_name,
            'email': email,
            'password_hash': password_hash,
            'company_name': company_name,
            'role': 'user',
            'is_active': True,
            'created_at': datetime.now(),
            'updated_at': datetime.now(),
            'last_login': None
        }

        # Insert into MongoDB
        result = users.insert_one(user_data)

        # Auto login
        session['user_id'] = str(result.inserted_id)
        session['user_email'] = email
        session['user_name'] = full_name
        session['user_role'] = 'user'

        return jsonify({
            'success': True,
            'message': 'Account created successfully',
            'user': {
                'id': str(result.inserted_id),
                'name': full_name,
                'email': email
            }
        })

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500 

@app.route('/api/logout')
def logout():
    session.clear()
    return redirect(url_for('login_page'))

@app.route('/api/check-auth')
def check_auth():
    if 'user_id' in session:
        return jsonify({
            'authenticated': True,
            'user': {
                'id': session.get('user_id'),
                'name': session.get('user_name'),
                'email': session.get('user_email'),
                'role': session.get('user_role')
            }
        })
    return jsonify({'authenticated': False})

# ========================
# PASSWORD RESET ROUTES
# ========================

@app.route('/forgot-password')
def forgot_password_page():
    return render_template('forgot_password.html')

@app.route('/reset-password/<token>')
def reset_password_page(token):
    try:
        # Verify token
        email = serializer.loads(
            token,
            salt='password-reset-salt',
            max_age=Config.PASSWORD_RESET_EXPIRY
        )
        return render_template('reset_password.html', token=token, email=email)
    except:
        return render_template('reset_password.html', token=None, error="Invalid or expired reset link")

@app.route('/api/forgot-password', methods=['POST'])
def forgot_password():
    try:
        data = request.json
        email = data.get('email')

        if not email:
            return jsonify({'success': False, 'message': 'Email is required'}), 400

        # Check if user exists in database
        users = MongoDB.get_collection('users')
        user = users.find_one({'email': email, 'is_active': True})

        if user:
            # Generate reset token
            token = serializer.dumps(
                email,
                salt='password-reset-salt'
            )

            # Store token in database (optional, for tracking)
            password_resets = MongoDB.get_collection('password_resets')

            reset_data = {
                'email': email,
                'token': token,
                'created_at': datetime.now(),
                'expires_at': datetime.now() + timedelta(seconds=Config.PASSWORD_RESET_EXPIRY),
                'used': False
            }

            password_resets.insert_one(reset_data)

            # Send reset email
            reset_url = f"{request.host_url}myob/reset-password/{token}"

            try:
                msg = Message(
                    subject="Password Reset Request - MYOB Data Extractor",
                    recipients=[email],
                    html=f"""
                    <h2>Password Reset Request</h2>
                    <p>You requested to reset your password for MYOB Data Extractor.</p>
                    <p>Click the link below to reset your password:</p>
                    <p><a href="{reset_url}">{reset_url}</a></p>
                    <p>This link will expire in 1 hour.</p>
                    <p>If you didn't request this, please ignore this email.</p>
                    <br>
                    <p>Best regards,<br>MYOB Data Extractor Team</p>
                    """
                )
                mail.send(msg)
            except Exception as e:
                print(f"Email sending failed: {e}")
                # For development, return the reset URL directly
                if app.debug:
                    return jsonify({
                        'success': True,
                        'message': 'Reset link generated (email not configured)',
                        'reset_url': reset_url
                    })

            return jsonify({
                'success': True,
                'message': 'Password reset instructions have been sent to your email'
            })
        else:
            # For security, don't reveal if email exists
            return jsonify({
                'success': True,
                'message': 'If your email is registered, you will receive reset instructions shortly'
            })

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/reset-password', methods=['POST'])
def reset_password():
    try:
        data = request.json
        token = data.get('token')
        new_password = data.get('new_password')
        confirm_password = data.get('confirm_password')

        if not token or not new_password or not confirm_password:
            return jsonify({'success': False, 'message': 'All fields are required'}), 400

        if new_password != confirm_password:
            return jsonify({'success': False, 'message': 'Passwords do not match'}), 400

        # Verify token
        try:
            email = serializer.loads(
                token,
                salt='password-reset-salt',
                max_age=Config.PASSWORD_RESET_EXPIRY
            )
        except:
            return jsonify({'success': False, 'message': 'Invalid or expired reset link'}), 400

        # Check if token was already used
        password_resets = MongoDB.get_collection('password_resets')
        reset_record = password_resets.find_one({
            'token': token,
            'email': email,
            'used': False,
            'expires_at': {'$gt': datetime.now()}
        })

        if not reset_record:
            return jsonify({'success': False, 'message': 'Invalid or expired reset link'}), 400

        # Update user password
        users = MongoDB.get_collection('users')

        # Hash new password
        password_hash = hash_password(new_password)

        # Update password
        result = users.update_one(
            {'email': email},
            {'$set': {
                'password_hash': password_hash,
                'updated_at': datetime.now()
            }}
        )

        if result.modified_count > 0:
            # Mark token as used
            password_resets.update_one(
                {'_id': reset_record['_id']},
                {'$set': {'used': True}}
            )

            return jsonify({
                'success': True,
                'message': 'Password has been reset successfully. You can now login with your new password.'
            })
        else:
            return jsonify({'success': False, 'message': 'User not found or password update failed'}), 400

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# ========================
# MYOB CONNECTION ROUTES
# ========================

@app.route('/api/myob/status')
@login_required
def myob_status():
    try:
        user_id = session['user_id']

        # Check MongoDB for MYOB connection
        connections = MongoDB.get_collection('myob_connections')
        connection = connections.find_one({
            'user_id': user_id,
            'connection_status': 'connected'
        })

        if connection:
            # Check if token is expired
            expires_at = connection.get('token_expires_at')
            if expires_at and datetime.now() > expires_at:
                # Token expired
                connections.update_one(
                    {'_id': connection['_id']},
                    {'$set': {'connection_status': 'disconnected'}}
                )
                return jsonify({'connected': False})

            # Return connection info based on API type
            response_data = {
                'connected': True,
                'api_type': connection.get('api_type', 'business')
            }

            if connection.get('api_type') == 'business':
                response_data['business_name'] = connection.get('business_name')
                response_data['business_id'] = connection.get('business_id')
            else:
                response_data['company_name'] = connection.get('company_name')
                response_data['company_id'] = connection.get('company_file_id')

            return jsonify(response_data)
        else:
            return jsonify({'connected': False})

    except Exception as e:
        return jsonify({'connected': False, 'error': str(e)}), 500

@app.route('/api/myob/disconnect', methods=['POST'])
@login_required
def disconnect_myob():
    try:
        user_id = session['user_id']

        connections = MongoDB.get_collection('myob_connections')
        connections.update_one(
            {'user_id': user_id},
            {'$set': {
                'connection_status': 'disconnected',
                'updated_at': datetime.now()
            }}
        )

        return jsonify({'success': True, 'message': 'Disconnected from MYOB'})

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# ========================
# MYOB BUSINESS API ROUTES
# ========================

@app.route('/connect')
@login_required
def connect_myob():
    """Connect to MYOB Business API"""
    try:
        if 'user_id' not in session:
            return redirect(url_for('login_page'))

        user_id = session['user_id']

        # Generate state with user_id embedded
        state = f"{user_id}_{str(uuid.uuid4())}"

        # Store in session
        session['myob_oauth_state'] = state
        session.modified = True

        # Save to database for later verification
        MongoDB.save_oauth_state(user_id, state)

        print(f"✅ MYOB Connect - User: {user_id}, State: {state}")

        # Save current session to database
        MongoDB.save_user_session(user_id, {
            'user_id': user_id,
            'email': session.get('user_email'),
            'name': session.get('user_name'),
            'role': session.get('user_role', 'user')
        })

        auth_url = MYOBBusinessAPI.get_auth_url(state)
        return redirect(auth_url)

    except Exception as e:
        print(f"❌ Error in connect_myob: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/callback')
def myob_auth_code():
    """MYOB OAuth callback - restores session from database"""
    print("\n" + "="*50)
    print("DEBUG: MYOB AUTH CODE STARTED (V2 - Consolidated Fix)")
    print("MYOB CALLBACK PARAMS:", dict(request.args))
    print("="*50 + "\n")

    if request.args.get('error'):
        return jsonify({
            'oauth_error': request.args.get('error'),
            'description': request.args.get('error_description')
        }), 400

    code = request.args.get('code')
    state = request.args.get('state')
    business_id = request.args.get('businessId')
    business_name = request.args.get('businessName')

    if not state:
        return "State parameter missing", 400

    # Extract user_id from state (format: "user_id_uuid")
    try:
        user_id = state.split('_')[0]
    except:
        return "Invalid state format", 400

    # Verify state exists in database
    oauth_state = MongoDB.verify_oauth_state(state)
    if not oauth_state:
        return "Invalid or expired OAuth state", 400

    # Restore session from database
    session_data = MongoDB.get_user_session(user_id)
    print(f"DEBUG: Session data from DB for {user_id}: {session_data}")

    if session_data:
        # Don't use session.clear() as it might mess with Flask-Session ID
        print(f"DEBUG: Session ID before restoration: {getattr(session, 'sid', 'No SID')}")
        session['user_id'] = str(session_data.get('user_id'))
        session['user_email'] = session_data.get('email')
        session['user_name'] = session_data.get('name')
        session['user_role'] = session_data.get('role', 'user')
        session.permanent = True
        session.modified = True
        print(f"✅ Session restored and marked permanent for user: {user_id}")
        print(f"DEBUG: Session content after restoration: {dict(session)}")
    else:
        print(f"❌ Session NOT found in DB for user: {user_id}")
        return f"Session not found for user {user_id}. Please login again.", 400

    if not business_id:
        return "businessId missing – Admin user & prompt=consent required", 400

    token_data = MYOBBusinessAPI.exchange_code_for_token(code)
    if not token_data:
        return "Token exchange failed", 400

    # Ensure expires_in is an integer to avoid TypeError in timedelta
    try:
        raw_expires_in = token_data.get('expires_in', 1200)
        print(f"DEBUG: raw_expires_in type: {type(raw_expires_in)}, value: {raw_expires_in}")
        expires_in = int(raw_expires_in)
    except (ValueError, TypeError) as e:
        print(f"DEBUG: Error casting expires_in: {e}. Defaulting to 1200.")
        expires_in = 1200

    expires_at = datetime.now() + timedelta(seconds=expires_in)
    print(f"DEBUG: Token expires in {expires_in} seconds at {expires_at}")

    MongoDB.get_collection('myob_connections').update_one(
        {'user_id': user_id},
        {'$set': {
            'user_id': user_id,
            'business_id': business_id,
            'business_name': business_name,
            'access_token': token_data['access_token'],
            'refresh_token': token_data['refresh_token'],
            'token_expires_at': expires_at,
            'connection_status': 'connected',
            'api_type': 'business',
            'updated_at': datetime.now()
        }},
        upsert=True
    )

    print("✅ Connection saved to MongoDB successfully!")

    print(f"DEBUG: Redirecting to dashboard. Current session user_id: {session.get('user_id')}")
    return redirect(url_for('dashboard'))

@app.route('/myob/select-business', methods=['POST'])
@login_required
def select_myob_business():
    """Select a MYOB business and save connection"""
    try:
        user_id = session['user_id']
        business_id = request.form.get('business_id')
        businesses = session.get('myob_businesses', [])
        token_data = session.get('myob_token_data')

        if not token_data:
            return "Token data not found", 400

        # Find selected business
        selected_business = next(
            (b for b in businesses if b.get('id') == business_id),
            None
        )

        if not selected_business:
            return "Selected business not found", 404

        # Calculate token expiry
        expires_at = datetime.now() + timedelta(seconds=token_data.get('expires_in', 3600))

        # Save to MongoDB
        connections = MongoDB.get_collection('myob_connections')

        connection_data = {
            'user_id': user_id,
            'business_id': business_id,
            'business_name': selected_business.get('name'),
            'access_token': token_data.get('access_token'),
            'refresh_token': token_data.get('refresh_token'),
            'token_expires_at': expires_at,
            'connection_status': 'connected',
            'api_type': 'business',
            'created_at': datetime.now(),
            'updated_at': datetime.now()
        }

        # Update or insert connection
        connections.update_one(
            {'user_id': user_id},
            {'$set': connection_data},
            upsert=True
        )

        # Clear session data
        session.pop('myob_token_data', None)
        session.pop('myob_businesses', None)
        session.pop('myob_auth_state', None)

        return redirect(url_for('dashboard'))

    except Exception as e:
        return f"Error: {str(e)}", 500

@app.route('/api/myob/business/customers')
@login_required
def get_business_customers():
    """API endpoint to get customers from MYOB Business"""
    try:
        user_id = session['user_id']

        # Get connection from database
        connections = MongoDB.get_collection('myob_connections')
        connection = connections.find_one({
            'user_id': user_id,
            'connection_status': 'connected',
            'api_type': 'business'
        })

        if not connection:
            return jsonify({'error': 'No active MYOB Business connection'}), 400

        # Initialize API client
        access_token, business_id = get_valid_myob_token(session['user_id'])

        api_client = MYOBBusinessAPI(
            access_token=access_token,
            business_id=business_id
        )

        # Get parameters
        page = request.args.get('page', 1, type=int)
        page_size = request.args.get('page_size', 100, type=int)

        # Fetch customers
        customers = api_client.get_customers(page=page, page_size=page_size)

        if customers:
            return jsonify({
                'success': True,
                'customers': customers.get('items', []),
                'pagination': customers.get('pagination', {})
            })
        else:
            return jsonify({'success': False, 'error': 'Failed to fetch customers'}), 500

    except Exception as e:
        print(f"Failed to fetch customers: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ========================
# DASHBOARD & DATA EXTRACTION
# ========================

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('index.html')

@app.route('/api/user-info')
@login_required
def user_info():
    try:
        user_id = session['user_id']

        users = MongoDB.get_collection('users')
        user = users.find_one({'_id': ObjectId(user_id)})

        if user:
            return jsonify({
                'id': str(user['_id']),
                'full_name': user['full_name'],
                'email': user['email'],
                'company_name': user.get('company_name', ''),
                'role': user.get('role', 'user')
            })
        return jsonify({'error': 'User not found'}), 404

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/dashboard/stats')
@login_required
def dashboard_stats():
    """Get aggregated stats for dashboard from history"""
    try:
        user_id = session['user_id']
        history_col = MongoDB.get_collection('extraction_history')

        # Aggregate stats
        pipeline = [
            {'$match': {'user_id': user_id, 'status': 'completed'}},
            {'$group': {
                '_id': '$extraction_type',
                'count': {'$sum': '$records_extracted'}
            }}
        ]

        stats = list(history_col.aggregate(pipeline))

        # Format response
        response = {
            'invoices': 0,
            'bills': 0,
            'payments': 0,
            'total': 0
        }

        for item in stats:
            count = item.get('count', 0)
            response['total'] += count

            type_id = item['_id']
            if type_id == 'invoices' or type_id.startswith('invoice_'):
                response['invoices'] += count
            elif type_id == 'bills' or type_id.startswith('bill_'):
                response['bills'] += count
            elif 'payment' in type_id:
                response['payments'] += count

        # Get Trends (Last 30 days)
        thirty_days_ago = datetime.now() - timedelta(days=30)
        trends_pipeline = [
            {'$match': {
                'user_id': user_id,
                'status': 'completed',
                'created_at': {'$gte': thirty_days_ago}
            }},
            {'$group': {
                '_id': {'$dateToString': {'format': '%Y-%m-%d', 'date': '$created_at'}},
                'count': {'$sum': '$records_extracted'}
            }},
            {'$sort': {'_id': 1}}
        ]

        trends = list(history_col.aggregate(trends_pipeline))

        return jsonify({
            'success': True,
            'stats': response,
            'trends': {
                'labels': [t['_id'] for t in trends],
                'data': [t['count'] for t in trends]
            }
        })

    except Exception as e:
        print(f"Stats Error: {e}")
        return jsonify({'success': False, 'stats': {'invoices': 0, 'bills': 0, 'payments': 0, 'total': 0}}), 500


@app.route('/api/extract', methods=['POST'])
@login_required
def extract_data():
    """Extract REAL data from MYOB Business API (Auto token refresh enabled)"""
    try:
        data = request.json
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        data_type = data.get('data_type', 'invoices')
        output_format = data.get('format', 'qbo')

        user_id = session['user_id']

        # -------------------------
        # BASIC VALIDATION
        # -------------------------
        if not start_date or not end_date:
            return jsonify({'success': False, 'message': 'Date range required'}), 400

        # Ensure dates are in YYYY-MM-DD format
        try:
            # Validate dates
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            end_dt = datetime.strptime(end_date, '%Y-%m-%d')

            if start_date > end_date:
                return jsonify({'success': False, 'message': 'Start date cannot be after end date'}), 400
        except ValueError as e:
            return jsonify({'success': False, 'message': f'Invalid date format: {e}'}), 400

        print(f"DEBUG: Extracting {data_type} from {start_date} to {end_date}")
        # -------------------------
        # AUTO REFRESH TOKEN HERE
        # -------------------------
        from utils.myob_token_middleware import get_valid_myob_token

        access_token, business_id = get_valid_myob_token(user_id)

        api_client = MYOBBusinessAPI(
            access_token=access_token,
            business_id=business_id
        )

        extracted_data = {}

        # -------------------------
        # DATA EXTRACTION LOGIC
        # -------------------------

        if data_type == 'invoice_payments':
            res = api_client.get_invoice_payments(start_date=start_date, end_date=end_date)
            if res and 'Items' in res:
                extracted_data['invoice_payments'] = res['Items']

        elif data_type == 'bill_payments':
            res = api_client.get_bill_payments(start_date=start_date, end_date=end_date)
            if res and 'Items' in res:
                extracted_data['bill_payments'] = res['Items']

        elif data_type == 'credit_notes':
            # Credit notes from invoices where TotalAmount is negative
            res = api_client.get_credit_notes(start_date=start_date, end_date=end_date)
            if res and 'Items' in res:
                extracted_data['credit_notes'] = res['Items']

        elif data_type == 'vendor_credits':
            res = api_client.get_vendor_credits(start_date=start_date, end_date=end_date)
            if res and 'Items' in res:
                extracted_data['vendor_credits'] = res['Items']

        elif data_type.startswith('invoice_'):
            inv_type = data_type.split('_')[1].capitalize()
            res = api_client.get_invoices(invoice_type=inv_type, start_date=start_date, end_date=end_date)
            if res and 'Items' in res:
                extracted_data['invoices'] = res['Items']

        elif data_type.startswith('bill_'):
            bill_type = data_type.split('_')[1].capitalize()
            res = api_client.get_bills(bill_type=bill_type, start_date=start_date, end_date=end_date)
            if res and 'Items' in res:
                extracted_data['bills'] = res['Items']

        elif data_type == 'all':
            all_invoices = []
            invoice_types = ['Item', 'Service', 'Professional', 'TimeBilling', 'Miscellaneous']
            for inv_type in invoice_types:
                res_inv = api_client.get_invoices(invoice_type=inv_type, start_date=start_date, end_date=end_date)
                if res_inv and 'Items' in res_inv:
                    all_invoices.extend(res_inv['Items'])
            if all_invoices:
                extracted_data['invoices'] = all_invoices

            all_bills = []
            bill_types = ['Item', 'Service', 'Professional', 'Miscellaneous']
            for bill_type in bill_types:
                res_bill = api_client.get_bills(bill_type=bill_type, start_date=start_date, end_date=end_date)
                if res_bill and 'Items' in res_bill:
                    all_bills.extend(res_bill['Items'])
            if all_bills:
                extracted_data['bills'] = all_bills

        elif data_type == 'invoices':
            all_invoices = []
            invoice_types = ['Item', 'Service', 'Professional', 'TimeBilling', 'Miscellaneous']

            for inv_type in invoice_types:
                print(f"Fetching invoices of type: {inv_type}")
                res = api_client.get_invoices(invoice_type=inv_type, start_date=start_date, end_date=end_date)
                if res and 'Items' in res:
                    print(f"  Found {len(res['Items'])} {inv_type} invoices")
                    all_invoices.extend(res['Items'])

            if all_invoices:
                extracted_data['invoices'] = all_invoices
                print(f"Total invoices extracted: {len(all_invoices)}")

        elif data_type == 'bills':
            all_bills = []
            bill_types = ['Item', 'Service', 'Professional', 'Miscellaneous']

            for bill_type in bill_types:
                print(f"Fetching bills of type: {bill_type}")
                res = api_client.get_bills(bill_type=bill_type, start_date=start_date, end_date=end_date)
                if res and 'Items' in res:
                    print(f"  Found {len(res['Items'])} {bill_type} bills")
                    all_bills.extend(res['Items'])

            if all_bills:
                extracted_data['bills'] = all_bills
                print(f"Total bills extracted: {len(all_bills)}")

        elif data_type == 'payments':
            res_inv_p = api_client.get_invoice_payments(start_date=start_date, end_date=end_date)
            if res_inv_p and 'Items' in res_inv_p:
                extracted_data['invoice_payments'] = res_inv_p['Items']

            res_bill_p = api_client.get_bill_payments(start_date=start_date, end_date=end_date)
            if res_bill_p and 'Items' in res_bill_p:
                extracted_data['bill_payments'] = res_bill_p['Items']

        # -------------------------
        # NO DATA CHECK
        # -------------------------
        total_records = sum(len(v) for v in extracted_data.values())
        if total_records == 0:
            return jsonify({
                'success': False,
                'message': 'No data found for selected criteria'
            }), 404

        # -------------------------
        # CONVERT FORMATS (RAW & TARGET)
        # -------------------------
        raw_data = ConverterFactory.convert(extracted_data, data_type, 'raw')
        converted_data = ConverterFactory.convert(extracted_data, data_type, output_format)

        # -------------------------
        # ADD ORGANIZATION NAME
        # -------------------------
        connections = MongoDB.get_collection('myob_connections')
        connection = connections.find_one({'user_id': user_id})

        org_name = 'Unknown Organization'
        if connection:
            org_name = connection.get('business_name') or connection.get('company_name') or 'Unknown Organization'

        # -------------------------
        # SAVE FILES (CSV, EXCEL, JSON)
        # -------------------------
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        import re
        safe_org_name = re.sub(r'[^a-zA-Z0-9]', '_', org_name).strip('_')
        base_name = f"{safe_org_name}_{data_type}_{timestamp}"

        myob_csv_filename = f"myob_{base_name}.csv"
        myob_xlsx_filename = f"myob_{base_name}.xlsx"
        myob_json_filename = f"myob_{base_name}.json"

        format_upper = output_format.upper()
        converted_csv_filename = f"{format_upper}_{base_name}.csv"
        converted_xlsx_filename = f"{format_upper}_{base_name}.xlsx"
        converted_json_filename = f"{format_upper}_{base_name}.json"

        myob_csv_filepath = f"static/exports/{myob_csv_filename}"
        myob_xlsx_filepath = f"static/exports/{myob_xlsx_filename}"
        myob_json_filepath = f"static/exports/{myob_json_filename}"

        converted_csv_filepath = f"static/exports/{converted_csv_filename}"
        converted_xlsx_filepath = f"static/exports/{converted_xlsx_filename}"
        converted_json_filepath = f"static/exports/{converted_json_filename}"

        raw_df = pd.DataFrame(raw_data)
        converted_df = pd.DataFrame(converted_data)
             
        #if not raw_df.empty: 
            #raw_df.insert(0, 'Organization Name', org_name)   
        #if not converted_df.empty:    
            #converted_df.insert(0, 'Organization Name', org_name)
        
        raw_df.to_csv(myob_csv_filepath, index=False)  
        raw_df.to_excel(myob_xlsx_filepath, sheet_name='myob sheet', index=False, engine='openpyxl')
        raw_df.to_json(myob_json_filepath, orient='records', indent=2)
 
        converted_df.to_csv(converted_csv_filepath, index=False)
        converted_df.to_excel(converted_xlsx_filepath, sheet_name='myob sheet', index=False, engine='openpyxl')
        converted_df.to_json(converted_json_filepath, orient='records', indent=2)

        # -------------------------
        # SAVE HISTORY
        # -------------------------
        MongoDB.get_collection('extraction_history').insert_one({
            'user_id': user_id,
            'extraction_type': data_type,
            'start_date': start_date,
            'end_date': end_date,
            'output_format': output_format,
            'records_extracted': len(converted_data),
            'file_path': converted_csv_filepath,
            'raw_file_path': myob_csv_filepath,
            'xlsx_file_path': converted_xlsx_filepath,
            'raw_xlsx_file_path': myob_xlsx_filepath,
            'json_file_path': converted_json_filepath,
            'raw_json_file_path': myob_json_filepath,
            'api_type': 'business',
            'status': 'completed',
            'created_at': datetime.now()
        })

        return jsonify({
            'success': True,
            'message': f'✅ Successfully extracted {len(converted_data)} records',
            'filename': converted_csv_filename,
            'download_url': f'/download/{converted_csv_filename}',
            'raw_filename': myob_csv_filename,
            'raw_download_url': f'/download/{myob_csv_filename}',
            'xlsx_filename': converted_xlsx_filename,
            'xlsx_download_url': f'/download/{converted_xlsx_filename}',
            'raw_xlsx_filename': myob_xlsx_filename,
            'raw_xlsx_download_url': f'/download/{myob_xlsx_filename}',
            'json_filename': converted_json_filename,
            'json_download_url': f'/download/{converted_json_filename}',
            'raw_json_filename': myob_json_filename,
            'raw_json_download_url': f'/download/{myob_json_filename}',
            'total_records': len(converted_data),
            'data_type': data_type,
            'format': output_format
        })

    except Exception as e:
        print("EXTRACTION ERROR:", str(e))
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/download/<filename>')
@login_required
def download_file(filename):
    filepath = f"static/exports/{filename}"
    if os.path.exists(filepath):
        return send_file(filepath, as_attachment=True)
    return jsonify({'error': 'File not found'}), 404

@app.route('/api/history')
@login_required
def extraction_history():
    try:
        user_id = session['user_id']

        history = MongoDB.get_collection('extraction_history')

        history_records = list(history.find(
            {'user_id': user_id}
        ).sort('created_at', -1).limit(10))

        for record in history_records:
            record['_id'] = str(record['_id'])
            if 'created_at' in record and isinstance(record['created_at'], datetime):
                record['created_at'] = record['created_at'].isoformat()

        return jsonify({'history': history_records})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ========================
# HEALTH CHECK
# ========================

@app.route('/health')
def health_check():
    try:
        client = MongoDB.get_client()
        client.admin.command('ping')
        db_ok = True

        return jsonify({
            'status': 'healthy',
            'database': 'connected' if db_ok else 'disconnected',
            'timestamp': datetime.now().isoformat(),
            'myob_configured': bool(Config.MYOB_CLIENT_ID),
            'database_type': 'MongoDB'
        })
    except Exception as e:
        return jsonify({'status': 'unhealthy', 'error': str(e)}), 500

# ========================
# ERROR HANDLERS
# ========================

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

# ========================
# JSON ENCODER FOR MONGO OBJECTID
# ========================

from flask.json.provider import DefaultJSONProvider
from bson import ObjectId
from datetime import datetime
import json


class MongoJSONEncoder(DefaultJSONProvider):
    def default(self, obj):
        if isinstance(obj, ObjectId):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)

    def dumps(self, obj, **kwargs):
        return json.dumps(obj, default=self.default, **kwargs)


app.json = MongoJSONEncoder(app)

# ========================
# APPLICATION STARTUP
# ========================

if __name__ == '__main__':
    init_database()

    print("=" * 50)
    print("MYOB Data Extractor - MongoDB Version")
    print("=" * 50)
    print(f"MongoDB: {Config.MONGO_URI}{Config.MONGO_DB}")
    print(f"MYOB Business API: {'Configured' if Config.MYOB_CLIENT_ID else 'Not configured'}")
    print("Starting server on http://localhost:2002")
    print("=" * 50)

    app.run(host='0.0.0.0', port=2002, debug=True)
 
    
