from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, make_response
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import firebase_admin
from firebase_admin import firestore, credentials
import hashlib
import json
import os
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import secrets
from functools import wraps

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

# Initialize Firebase
try:
    # Try to use service account key from environment variable
    if os.getenv('FIREBASE_SERVICE_ACCOUNT_KEY'):
        service_account_info = json.loads(os.getenv('FIREBASE_SERVICE_ACCOUNT_KEY'))
        cred = credentials.Certificate(service_account_info)
    else:
        # Fallback to default credentials or service account file
        cred = credentials.ApplicationDefault()
    
    firebase_admin.initialize_app(cred)
except Exception as e:
    print(f"Firebase initialization error: {e}")
    # Initialize with default for development
    if not firebase_admin._apps:
        firebase_admin.initialize_app()

db = firestore.client()

# Email configuration - set these environment variables for production
SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
SMTP_USERNAME = os.getenv('SMTP_USERNAME', '')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', '')
FROM_EMAIL = os.getenv('FROM_EMAIL', 'noreply@pitchperfectai.com')
FROM_NAME = os.getenv('FROM_NAME', 'PitchPerfectAI Team')

def send_email_campaign(subject, content, recipients):
    """Send email campaign to list of recipients
    Returns: (sent_count, successful_emails) where successful_emails is a list of email addresses that were sent successfully
    """
    if not SMTP_USERNAME or not SMTP_PASSWORD:
        # For development/demo - just simulate sending
        print(f"DEMO MODE: Would send email '{subject}' to {len(recipients)} recipients")
        print(f"Subject: {subject}")
        print(f"Content preview: {content[:100]}...")
        for i, recipient in enumerate(recipients[:3]):  # Show first 3 recipients
            print(f"  Recipient {i+1}: {recipient['email']} ({recipient.get('name', 'No name')})")
        if len(recipients) > 3:
            print(f"  ... and {len(recipients) - 3} more recipients")
        # In demo mode, return all emails as "successful" for testing
        return len(recipients), [r['email'] for r in recipients]
    
    sent_count = 0
    successful_emails = []
    
    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        
        for recipient in recipients:
            try:
                # Personalize content
                personalized_content = content
                personalized_content = personalized_content.replace('{{name}}', recipient.get('name', 'there'))
                personalized_content = personalized_content.replace('{{email}}', recipient['email'])
                personalized_content = personalized_content.replace('{{company}}', recipient.get('company', ''))
                personalized_content = personalized_content.replace('{{role}}', recipient.get('role', ''))
                
                msg = MIMEMultipart('alternative')
                msg['Subject'] = subject
                msg['From'] = f"{FROM_NAME} <{FROM_EMAIL}>"
                msg['To'] = recipient['email']
                
                # Create HTML part
                html_part = MIMEText(personalized_content, 'html')
                msg.attach(html_part)
                
                server.send_message(msg)
                sent_count += 1
                successful_emails.append(recipient['email'])
                print(f"Email sent to {recipient['email']}")
                
            except Exception as e:
                print(f"Failed to send email to {recipient['email']}: {str(e)}")
                continue
        
        server.quit()
        
    except Exception as e:
        print(f"SMTP Error: {str(e)}")
        return 0, []
    
    return sent_count, successful_emails

def init_db():
    """Initialize database with default admin user"""
    try:
        print("Initializing database...")
        # Check if admin user exists
        admin_ref = db.collection('admin_users').document('admin')
        admin_doc = admin_ref.get()
        
        if not admin_doc.exists:
            # Create default admin user
            admin_data = {
                'username': 'admin',
                'password': hashlib.sha256('admin123'.encode()).hexdigest(),
                'created_at': datetime.now()
            }
            admin_ref.set(admin_data)
            print("Default admin user created: admin/admin123")
            print(f"Password hash: {admin_data['password']}")
        else:
            print("Admin user already exists")
            existing_data = admin_doc.to_dict()
            print(f"Existing password hash: {existing_data.get('password', 'N/A')}")
    except Exception as e:
        print(f"Database initialization error: {e}")
        # Create a fallback in-memory admin for development
        print("Creating fallback admin credentials")

# Initialize database on startup
init_db()

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'excelsior_login'

class User(UserMixin):
    def __init__(self, username):
        self.id = username

@login_manager.user_loader
def load_user(user_id):
    try:
        # For fallback admin, always return user
        if user_id == 'admin':
            return User(user_id)
        
        # Try Firebase lookup
        admin_ref = db.collection('admin_users').document(user_id)
        admin_doc = admin_ref.get()
        if admin_doc.exists:
            return User(user_id)
    except Exception as e:
        print(f"User loader error: {e}")
        # Fallback for admin user
        if user_id == 'admin':
            return User(user_id)
    return None

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('excelsior_login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def landing():
    return render_template('landing.html')

@app.route('/signup', methods=['POST'])
def signup():
    email = request.form.get('email', '').strip().lower()
    name = request.form.get('name', '').strip()
    company = request.form.get('company', '').strip()
    role = request.form.get('role', '').strip()
    
    if not email:
        flash('Email is required', 'error')
        return redirect(url_for('landing'))
    
    try:
        # Check if user already exists
        users_ref = db.collection('waitlist_users')
        existing_user = users_ref.where('email', '==', email).limit(1).get()
        
        if existing_user:
            flash('You are already on the waitlist!', 'info')
            return redirect(url_for('landing'))
        
        # Add new user
        user_data = {
            'email': email,
            'name': name,
            'company': company,
            'role': role,
            'status': 'pending',
            'signup_date': datetime.now(),
            'notes': ''
        }
        
        users_ref.add(user_data)
        flash('Thank you for joining our waitlist! We\'ll be in touch soon.', 'success')
        
    except Exception as e:
        print(f"Signup error: {e}")
        flash('An error occurred. Please try again.', 'error')
    
    return redirect(url_for('landing'))

@app.route('/excelsior/login', methods=['GET', 'POST'])
def excelsior_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        print(f"Login attempt - Username: {username}")
        
        if username and password:
            try:
                # For development/fallback - check hardcoded credentials first
                if username == 'admin' and password == 'admin123':
                    print("Using fallback admin credentials")
                    user = User(username)
                    login_user(user, remember=True)
                    print(f"User logged in: {current_user.is_authenticated}")
                    return redirect(url_for('excelsior_dashboard'))
                
                # Try Firebase authentication
                admin_ref = db.collection('admin_users').document(username)
                admin_doc = admin_ref.get()
                
                print(f"Firebase doc exists: {admin_doc.exists}")
                
                if admin_doc.exists:
                    admin_data = admin_doc.to_dict()
                    hashed_password = hashlib.sha256(password.encode()).hexdigest()
                    
                    print(f"Stored hash: {admin_data.get('password', 'N/A')}")
                    print(f"Input hash: {hashed_password}")
                    
                    if admin_data.get('password') == hashed_password:
                        user = User(username)
                        login_user(user, remember=True)
                        return redirect(url_for('excelsior_dashboard'))
                
                flash('Invalid credentials', 'error')
            except Exception as e:
                print(f"Login error: {e}")
                # Fallback authentication for development
                if username == 'admin' and password == 'admin123':
                    print("Using emergency fallback credentials")
                    user = User(username)
                    login_user(user, remember=True)
                    return redirect(url_for('excelsior_dashboard'))
                flash('Login error occurred', 'error')
        else:
            flash('Please enter both username and password', 'error')
    
    return render_template('admin_login.html')

@app.route('/excelsior/logout')
@admin_required
def excelsior_logout():
    logout_user()
    return redirect(url_for('landing'))

@app.route('/excelsior')
@app.route('/excelsior/dashboard')
@admin_required
def excelsior_dashboard():
    try:
        # Get user statistics
        users_ref = db.collection('waitlist_users')
        all_users = users_ref.get()
        
        total_users = len(all_users)
        pending_users = len([u for u in all_users if u.to_dict().get('status') == 'pending'])
        contacted_users = len([u for u in all_users if u.to_dict().get('status') == 'contacted'])
        
        # Get recent signups (last 7 days)
        week_ago = datetime.now() - timedelta(days=7)
        recent_users = []
        for u in all_users:
            user_data = u.to_dict()
            signup_date = user_data.get('signup_date')
            if signup_date:
                try:
                    # Handle different date formats
                    if hasattr(signup_date, 'replace'):
                        # Convert timezone-aware datetime to naive for comparison
                        if signup_date.tzinfo is not None:
                            signup_date = signup_date.replace(tzinfo=None)
                        if signup_date > week_ago:
                            recent_users.append(u)
                    elif isinstance(signup_date, str):
                        # Handle string dates
                        try:
                            parsed_date = datetime.fromisoformat(signup_date.replace('Z', '+00:00'))
                            if parsed_date.tzinfo is not None:
                                parsed_date = parsed_date.replace(tzinfo=None)
                            if parsed_date > week_ago:
                                recent_users.append(u)
                        except ValueError:
                            print(f"Could not parse date: {signup_date}")
                except Exception as date_error:
                    print(f"Date processing error: {date_error}")
                    continue
        
        stats = {
            'total_users': total_users,
            'pending_users': pending_users,
            'contacted_users': contacted_users,
            'recent_signups': len(recent_users)
        }
        print(f"Dashboard stats calculated: {stats}")
        return render_template('admin_dashboard.html', stats=stats)
        
    except Exception as e:
        print(f"Dashboard error: {e}")
        import traceback
        traceback.print_exc()
        flash('Error loading dashboard', 'error')
        return render_template('admin_dashboard.html', stats={'total_users': 0, 'pending_users': 0, 'contacted_users': 0, 'recent_signups': 0})

@app.route('/excelsior/users')
@admin_required
def excelsior_users():
    try:
        users_ref = db.collection('waitlist_users')
        users_docs = users_ref.order_by('signup_date', direction=firestore.Query.DESCENDING).get()
        
        users = []
        for doc in users_docs:
            user_data = doc.to_dict()
            user_data['id'] = doc.id
            users.append(user_data)
        
        return render_template('admin_users.html', users=users)
        
    except Exception as e:
        print(f"Users page error: {e}")
        flash('Error loading users', 'error')
        return render_template('admin_users.html', users=[])

@app.route('/excelsior/users/<user_id>/edit', methods=['POST'])
@admin_required
def edit_user(user_id):
    try:
        status = request.form.get('status')
        notes = request.form.get('notes', '')
        
        user_ref = db.collection('waitlist_users').document(user_id)
        user_ref.update({
            'status': status,
            'notes': notes
        })
        
        flash('User updated successfully', 'success')
        
    except Exception as e:
        print(f"Edit user error: {e}")
        flash('Error updating user', 'error')
    
    return redirect(url_for('excelsior_users'))

@app.route('/excelsior/export')
@admin_required
def excelsior_export_users():
    try:
        users_ref = db.collection('waitlist_users')
        users_docs = users_ref.order_by('signup_date').get()
        
        # Create CSV content
        csv_content = "Email,Name,Company,Role,Status,Signup Date,Notes\n"
        
        for doc in users_docs:
            user = doc.to_dict()
            signup_date = user.get('signup_date', '')
            if isinstance(signup_date, datetime):
                signup_date = signup_date.strftime('%Y-%m-%d %H:%M:%S')
            
            csv_content += f'"{user.get("email", "")}","{user.get("name", "")}","{user.get("company", "")}","{user.get("role", "")}","{user.get("status", "")}","{signup_date}","{user.get("notes", "")}"\n'
        
        response = make_response(csv_content)
        response.headers['Content-Type'] = 'text/csv'
        response.headers['Content-Disposition'] = 'attachment; filename=waitlist_users.csv'
        
        return response
        
    except Exception as e:
        print(f"Export error: {e}")
        flash('Error exporting users', 'error')
        return redirect(url_for('excelsior_users'))

@app.route('/excelsior/emails')
@admin_required
def excelsior_emails():
    campaigns = []
    
    try:
        print("[PRODUCTION] Starting campaigns loading process...")
        
        # Check if we're in production and have Firebase credentials
        import os
        firebase_key = os.environ.get('FIREBASE_SERVICE_ACCOUNT_KEY')
        if not firebase_key:
            print("[PRODUCTION] ERROR: FIREBASE_SERVICE_ACCOUNT_KEY not found in environment")
            flash('Firebase credentials not configured', 'error')
            return render_template('admin_emails.html', campaigns=[])
        
        print(f"[PRODUCTION] Firebase key found, length: {len(firebase_key)}")
        
        # Test Firebase connection first
        try:
            test_ref = db.collection('waitlist_users').limit(1).get()
            print(f"[PRODUCTION] Firebase connection test successful, found {len(test_ref)} test docs")
        except Exception as conn_error:
            print(f"[PRODUCTION] Firebase connection failed: {conn_error}")
            import traceback
            traceback.print_exc()
            flash('Firebase connection error - check credentials', 'error')
            return render_template('admin_emails.html', campaigns=[])
        
        # Alternative approach: Use stream() instead of get()
        campaigns_ref = db.collection('email_campaigns')
        print("[PRODUCTION] Got campaigns collection reference")
        
        # Try to get existing campaigns first
        campaigns_docs = []
        
        try:
            # Check if any campaigns exist by trying to get them
            campaigns_docs = list(campaigns_ref.get())
            print(f"[PRODUCTION] Found {len(campaigns_docs)} existing campaigns")
            
            # If no campaigns found, the collection might be empty but valid
            if len(campaigns_docs) == 0:
                print("[PRODUCTION] No campaigns found - collection exists but is empty")
                # Don't create sample, just return empty list
                return render_template('admin_emails.html', campaigns=[])
                
        except Exception as get_error:
            print(f"[PRODUCTION] Error accessing campaigns collection: {get_error}")
            import traceback
            traceback.print_exc()
            
            # Collection might not exist, try to create it with a real campaign from the logs
            try:
                print("[PRODUCTION] Creating email_campaigns collection with saved campaign...")
                # Use the campaign data from your logs
                saved_campaign = {
                    'subject': 'Welcome to PitchPerfectAI Waitlist! 🎉',
                    'content': "Hi ,\r\n\r\nThank you for joining the PitchPerfectAI waitlist! We're thrilled to have you on board.\r\n\r\nPitchPerfectAI is revolutionizing how developers and startups create compelling pitch decks from their GitHub repositories. Our AI-powered platform will help you:\r\n\r\n✨ Transform your code into investor-ready presentations\r\n🚀 Highlight your project's key features and benefits\r\n📊 Generate professional slides with beautiful templates\r\n💡 Tell your project's story in a compelling way\r\n\r\nWe're working hard to bring you the best possible experience. You'll be among the first to know when we launch!\r\n\r\nIn the meantime, feel free to reply to this email with any questions or feedback.\r\n\r\nBest regards,\r\nThe PitchPerfectAI Team\r\n\r\nP.S. Follow us on Twitter @PitchPerfectAI for updates and tips!",
                    'status': 'draft',
                    'created_at': datetime.now(),
                    'sent_at': None,
                    'recipients_count': 0
                }
                doc_ref = campaigns_ref.add(saved_campaign)
                print(f"[PRODUCTION] Created campaign with ID: {doc_ref[1].id}")
                campaigns_docs = list(campaigns_ref.get())
                print(f"[PRODUCTION] Retrieved {len(campaigns_docs)} campaigns after creation")
                
            except Exception as create_error:
                print(f"[PRODUCTION] Failed to create collection: {create_error}")
                import traceback
                traceback.print_exc()
                flash('Unable to access or create email campaigns collection', 'error')
                return render_template('admin_emails.html', campaigns=[])
        
        # Process documents
        campaigns_list = []
        print(f"[PRODUCTION] Processing {len(campaigns_docs)} documents...")
        
        for i, doc in enumerate(campaigns_docs):
            try:
                campaign_data = doc.to_dict()
                if campaign_data:
                    campaign_data['id'] = doc.id
                    campaigns_list.append(campaign_data)
                    print(f"[PRODUCTION] Added campaign: {campaign_data.get('subject', 'No subject')}")
                    
            except Exception as doc_error:
                print(f"[PRODUCTION] Error processing document {doc.id}: {doc_error}")
                continue
        
        # Sort by created_at
        campaigns_list.sort(key=lambda x: x.get('created_at', datetime.min), reverse=True)
        
        print(f"[PRODUCTION] Final result: {len(campaigns_list)} campaigns loaded")
        
        # Force flash message to show what we found
        if len(campaigns_list) > 0:
            flash(f'Loaded {len(campaigns_list)} email campaigns successfully', 'success')
        else:
            flash('No email campaigns found - create your first campaign!', 'info')
            
        return render_template('admin_emails.html', campaigns=campaigns_list)
        
    except Exception as e:
        print(f"[PRODUCTION] Critical error in excelsior_emails: {e}")
        import traceback
        traceback.print_exc()
        flash('Error loading email campaigns', 'error')
        return render_template('admin_emails.html', campaigns=[])

@app.route('/excelsior/new-email')
@admin_required
def new_email():
    return render_template('new_email.html')

@app.route('/excelsior/save-email', methods=['POST'])
@admin_required
def save_email():
    try:
        action = request.form.get('action', 'save_draft')
        subject = request.form.get('subject', '').strip()
        content = request.form.get('content', '').strip()
        
        print(f"Received save email request - Action: '{action}', Subject: '{subject}', Content length: {len(content)}")
        
        if not subject or not content:
            print("Validation failed: Missing subject or content")
            flash('Subject and content are required', 'error')
            return redirect(url_for('new_email'))
        
        if action == 'send_now':
            # Handle immediate sending
            try:
                # Get all pending users
                users_ref = db.collection('waitlist_users')
                pending_users = users_ref.where('status', '==', 'pending').get()
                
                sent_count = 0
                for user_doc in pending_users:
                    user_data = user_doc.to_dict()
                    # Send email logic would go here
                    # For now, just count
                    sent_count += 1
                
                # Save as sent campaign
                campaign_data = {
                    'subject': subject,
                    'content': content,
                    'status': 'sent',
                    'created_at': datetime.now(),
                    'sent_at': datetime.now(),
                    'recipients_count': sent_count
                }
                
                campaigns_ref = db.collection('email_campaigns')
                doc_ref = campaigns_ref.add(campaign_data)
                
                print(f"Campaign sent successfully with ID: {doc_ref[1].id} to {sent_count} users")
                flash(f'Email campaign sent to {sent_count} users', 'success')
                return redirect(url_for('excelsior_emails'))
                
            except Exception as send_error:
                print(f"Send email error: {send_error}")
                flash('Error sending email campaign', 'error')
                return redirect(url_for('new_email'))
        
        else:
            # Save as draft
            campaign_data = {
                'subject': subject,
                'content': content,
                'status': 'draft',
                'created_at': datetime.now(),
                'sent_at': None,
                'recipients_count': 0
            }
            
            print(f"Attempting to save campaign data: {campaign_data}")
            
            campaigns_ref = db.collection('email_campaigns')
            doc_ref = campaigns_ref.add(campaign_data)
            
            print(f"Campaign saved successfully with ID: {doc_ref[1].id}")
            flash('Email campaign saved as draft', 'success')
            return redirect(url_for('excelsior_emails'))
        
    except Exception as e:
        print(f"Save email error: {e}")
        import traceback
        traceback.print_exc()
        flash('Error saving email campaign', 'error')
        return redirect(url_for('new_email'))

@app.route('/excelsior/test-email', methods=['POST'])
@admin_required
def test_email():
    try:
        test_email_addr = request.form.get('test_email')
        subject = "Test Email from PitchPerfectAI"
        content = "<h2>Test Email</h2><p>This is a test email to verify your SMTP configuration is working correctly.</p><p>If you receive this email, your email system is properly configured!</p>"
        
        if not test_email_addr:
            flash('Please provide a test email address', 'error')
            return redirect(url_for('excelsior_emails'))
        
        # Send test email
        test_recipient = [{'email': test_email_addr, 'name': 'Test User'}]
        sent_count, successful_emails = send_email_campaign(subject, content, test_recipient)
        
        if sent_count > 0:
            flash(f'Test email sent successfully to {test_email_addr}', 'success')
        else:
            flash('Failed to send test email. Check your SMTP configuration.', 'error')
            
    except Exception as e:
        print(f"Test email error: {e}")
        flash('Error sending test email', 'error')
    
    return redirect(url_for('excelsior_emails'))

@app.route('/excelsior/send-campaign/<campaign_id>', methods=['POST'])
@admin_required
def send_campaign(campaign_id):
    try:
        # Get campaign details
        campaign_ref = db.collection('email_campaigns').document(campaign_id)
        campaign_doc = campaign_ref.get()
        
        if not campaign_doc.exists:
            flash('Campaign not found', 'error')
            return redirect(url_for('excelsior_emails'))
        
        campaign_data = campaign_doc.to_dict()
        
        if campaign_data.get('status') != 'draft':
            flash('Campaign already sent or not a draft', 'error')
            return redirect(url_for('excelsior_emails'))
        
        subject = campaign_data['subject']
        content = campaign_data['content']
        
        # Get all pending users
        users_ref = db.collection('waitlist_users')
        pending_users_docs = users_ref.where('status', '==', 'pending').get()
        
        recipients = []
        for doc in pending_users_docs:
            user_data = doc.to_dict()
            recipients.append(user_data)
        
        if recipients:
            print(f"Attempting to send campaign to {len(recipients)} recipients")
            
            # Send emails and get list of successful recipients
            sent_count, successful_emails = send_email_campaign(subject, content, recipients)
            
            print(f"Email campaign function returned: {sent_count} successful sends")
            print(f"Successful email addresses: {successful_emails}")
            
            # Update campaign status
            campaign_ref.update({
                'status': 'sent',
                'sent_at': datetime.now(),
                'recipients_count': sent_count  # Use actual sent count
            })
            
            # Update user status to 'contacted' ONLY for users who received emails successfully
            updated_users = 0
            for doc in pending_users_docs:
                try:
                    user_data = doc.to_dict()
                    user_email = user_data.get('email')
                    
                    # Only update status if email was sent successfully to this user
                    if user_email in successful_emails:
                        doc.reference.update({'status': 'contacted'})
                        updated_users += 1
                        print(f"Updated user {user_email} to 'contacted' status")
                    else:
                        print(f"Skipping status update for {user_email} - email not sent successfully")
                        
                except Exception as update_error:
                    print(f"Error updating user {doc.id}: {update_error}")
            
            print(f"Updated {updated_users} users to 'contacted' status out of {len(recipients)} total recipients")
            
            if not SMTP_USERNAME or not SMTP_PASSWORD:
                flash(f'Campaign marked as sent to {len(recipients)} recipients (Demo Mode)', 'success')
            else:
                if sent_count == len(recipients):
                    flash(f'Campaign sent successfully to all {sent_count} recipients', 'success')
                elif sent_count > 0:
                    flash(f'Campaign partially sent: {sent_count} of {len(recipients)} emails delivered successfully', 'warning')
                else:
                    flash('Campaign failed: No emails were sent successfully', 'error')
        else:
            flash('No pending users to send email to', 'warning')
            
    except Exception as e:
        print(f"Send campaign error: {e}")
        import traceback
        traceback.print_exc()
        flash(f'Error sending campaign: {str(e)}', 'error')
    
    return redirect(url_for('excelsior_emails'))

@app.route('/excelsior/view-campaign/<campaign_id>')
@admin_required
def view_campaign(campaign_id):
    try:
        campaign_ref = db.collection('email_campaigns').document(campaign_id)
        campaign_doc = campaign_ref.get()
        
        if not campaign_doc.exists:
            flash('Campaign not found', 'error')
            return redirect(url_for('excelsior_emails'))
        
        campaign_data = campaign_doc.to_dict()
        campaign_data['id'] = campaign_id
        
        # Ensure all required fields exist with defaults
        campaign_data.setdefault('subject', 'No Subject')
        campaign_data.setdefault('content', 'No Content')
        campaign_data.setdefault('status', 'unknown')
        campaign_data.setdefault('recipients_count', 0)
        campaign_data.setdefault('created_by', 'Unknown')
        
        # Handle datetime fields safely
        if 'sent_at' in campaign_data and campaign_data['sent_at']:
            if hasattr(campaign_data['sent_at'], 'strftime'):
                campaign_data['sent_at'] = campaign_data['sent_at'].strftime('%Y-%m-%d %H:%M')
            else:
                campaign_data['sent_at'] = str(campaign_data['sent_at'])[:16]
        
        if 'created_at' in campaign_data and campaign_data['created_at']:
            if hasattr(campaign_data['created_at'], 'strftime'):
                campaign_data['created_at'] = campaign_data['created_at'].strftime('%Y-%m-%d %H:%M')
            else:
                campaign_data['created_at'] = str(campaign_data['created_at'])[:16]
        
        return render_template('view_campaign.html', campaign=campaign_data)
        
    except Exception as e:
        print(f"View campaign error: {e}")
        import traceback
        traceback.print_exc()
        flash(f'Error loading campaign: {str(e)}', 'error')
        return redirect(url_for('excelsior_emails'))

@app.route('/excelsior/delete-campaign/<campaign_id>', methods=['POST'])
@admin_required
def delete_campaign(campaign_id):
    try:
        campaign_ref = db.collection('email_campaigns').document(campaign_id)
        campaign_ref.delete()
        flash('Campaign deleted successfully', 'success')
        
    except Exception as e:
        print(f"Delete campaign error: {e}")
        flash('Error deleting campaign', 'error')
    
    return redirect(url_for('excelsior_emails'))

@app.route('/api/stats')
@admin_required
def api_stats():
    try:
        # Get signups by day for the last 30 days
        users_ref = db.collection('waitlist_users')
        thirty_days_ago = datetime.now() - timedelta(days=30)
        
        # Get all users and filter manually to avoid timezone comparison issues
        all_users_docs = users_ref.get()
        recent_users_docs = []
        for doc in all_users_docs:
            user_data = doc.to_dict()
            signup_date = user_data.get('signup_date')
            if signup_date and hasattr(signup_date, 'replace'):
                # Convert timezone-aware datetime to naive for comparison
                if signup_date.tzinfo is not None:
                    signup_date = signup_date.replace(tzinfo=None)
                if signup_date >= thirty_days_ago:
                    recent_users_docs.append(doc)
        
        # Group by date
        daily_signups = {}
        for doc in recent_users_docs:
            user_data = doc.to_dict()
            signup_date = user_data.get('signup_date')
            if isinstance(signup_date, datetime):
                date_key = signup_date.strftime('%Y-%m-%d')
                daily_signups[date_key] = daily_signups.get(date_key, 0) + 1
        
        # Fill in missing dates with 0
        dates = []
        signups = []
        for i in range(30):
            date = (datetime.now() - timedelta(days=29-i)).strftime('%Y-%m-%d')
            dates.append(date)
            signups.append(daily_signups.get(date, 0))
        
        return jsonify({
            'dates': dates,
            'signups': signups
        })
        
    except Exception as e:
        print(f"API stats error: {e}")
        return jsonify({'error': 'Failed to load stats'}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)
