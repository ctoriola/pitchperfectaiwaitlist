from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, make_response
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import hashlib
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import json
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
    """Send email campaign to list of recipients"""
    if not SMTP_USERNAME or not SMTP_PASSWORD:
        # For development/demo - just simulate sending
        print(f"DEMO MODE: Would send email '{subject}' to {len(recipients)} recipients")
        print(f"Subject: {subject}")
        print(f"Content preview: {content[:100]}...")
        for i, recipient in enumerate(recipients[:3]):  # Show first 3 recipients
            print(f"  Recipient {i+1}: {recipient['email']} ({recipient.get('name', 'No name')})")
        if len(recipients) > 3:
            print(f"  ... and {len(recipients) - 3} more recipients")
        return len(recipients)
    
    sent_count = 0
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
                print(f"Email sent to {recipient['email']}")
                
            except Exception as e:
                print(f"Failed to send email to {recipient['email']}: {str(e)}")
                continue
        
        server.quit()
        
    except Exception as e:
        print(f"SMTP Error: {str(e)}")
        return 0
    
    return sent_count

def init_db():
    """Initialize database with default admin user"""
    try:
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
    except Exception as e:
        print(f"Database initialization error: {e}")

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
        admin_ref = db.collection('admin_users').document(user_id)
        admin_doc = admin_ref.get()
        if admin_doc.exists:
            return User(user_id)
    except:
        pass
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
        
        if username and password:
            try:
                admin_ref = db.collection('admin_users').document(username)
                admin_doc = admin_ref.get()
                
                if admin_doc.exists:
                    admin_data = admin_doc.to_dict()
                    hashed_password = hashlib.sha256(password.encode()).hexdigest()
                    
                    if admin_data['password'] == hashed_password:
                        user = User(username)
                        login_user(user)
                        return redirect(url_for('excelsior_dashboard'))
                
                flash('Invalid credentials', 'error')
            except Exception as e:
                print(f"Login error: {e}")
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
        from datetime import timedelta
        week_ago = datetime.now() - timedelta(days=7)
        recent_users = [u for u in all_users if u.to_dict().get('signup_date', datetime.min) > week_ago]
        
        stats = {
            'total_users': total_users,
            'pending_users': pending_users,
            'contacted_users': contacted_users,
            'recent_signups': len(recent_users)
        }
        
        return render_template('admin_dashboard.html', stats=stats)
        
    except Exception as e:
        print(f"Dashboard error: {e}")
        flash('Error loading dashboard', 'error')
        return render_template('admin_dashboard.html', stats={})

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
def export_users():
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
    try:
        campaigns_ref = db.collection('email_campaigns')
        campaigns_docs = campaigns_ref.order_by('created_at', direction=firestore.Query.DESCENDING).get()
        
        campaigns = []
        for doc in campaigns_docs:
            campaign_data = doc.to_dict()
            campaign_data['id'] = doc.id
            campaigns.append(campaign_data)
        
        return render_template('admin_emails.html', campaigns=campaigns)
        
    except Exception as e:
        print(f"Emails page error: {e}")
        flash('Error loading campaigns', 'error')
        return render_template('admin_emails.html', campaigns=[])

@app.route('/excelsior/new-email')
@admin_required
def new_email():
    return render_template('new_email.html')

@app.route('/excelsior/save-email', methods=['POST'])
@admin_required
def save_email():
    try:
        subject = request.form.get('subject', '').strip()
        content = request.form.get('content', '').strip()
        
        if not subject or not content:
            flash('Subject and content are required', 'error')
            return redirect(url_for('new_email'))
        
        campaign_data = {
            'subject': subject,
            'content': content,
            'status': 'draft',
            'created_at': datetime.now(),
            'sent_at': None,
            'recipients_count': 0
        }
        
        campaigns_ref = db.collection('email_campaigns')
        campaigns_ref.add(campaign_data)
        
        flash('Email campaign saved as draft', 'success')
        return redirect(url_for('excelsior_emails'))
        
    except Exception as e:
        print(f"Save email error: {e}")
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
        sent_count = send_email_campaign(subject, content, test_recipient)
        
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
            # Send emails
            sent_count = send_email_campaign(subject, content, recipients)
            
            # Update campaign status
            campaign_ref.update({
                'status': 'sent',
                'sent_at': datetime.now(),
                'recipients_count': sent_count
            })
            
            # Update user status to 'contacted'
            for doc in pending_users_docs:
                doc.reference.update({'status': 'contacted'})
            
            flash(f'Campaign sent to {sent_count} recipients', 'success')
        else:
            flash('No pending users to send email to', 'warning')
            
    except Exception as e:
        print(f"Send campaign error: {e}")
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
        
        return render_template('view_campaign.html', campaign=campaign_data)
        
    except Exception as e:
        print(f"View campaign error: {e}")
        flash('Error loading campaign', 'error')
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
        from datetime import timedelta
        
        users_ref = db.collection('waitlist_users')
        thirty_days_ago = datetime.now() - timedelta(days=30)
        
        recent_users_docs = users_ref.where('signup_date', '>=', thirty_days_ago).get()
        
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
