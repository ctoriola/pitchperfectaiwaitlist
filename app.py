from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
import sqlite3
import threading
import hashlib
import secrets
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from functools import wraps
import re

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

# Database lock to prevent concurrent access issues
db_lock = threading.Lock()

def get_db_connection():
    """Get a database connection with proper timeout and WAL mode"""
    conn = sqlite3.connect('waitlist.db', timeout=30.0)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.execute('PRAGMA cache_size=1000')
    conn.execute('PRAGMA temp_store=MEMORY')
    return conn

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
            print(f"  Recipient {i+1}: {recipient[0]} ({recipient[1] or 'No name'})")
        if len(recipients) > 3:
            print(f"  ... and {len(recipients) - 3} more recipients")
        return len(recipients)
    
    sent_count = 0
    
    try:
        # Connect to SMTP server
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        
        for recipient in recipients:
            try:
                email = recipient[0]
                name = recipient[1] or 'Valued User'
                
                # Create personalized content
                company = recipient[2] if len(recipient) > 2 else ''
                role = recipient[3] if len(recipient) > 3 else ''
                
                personalized_content = personalize_email_content(content, {
                    'name': name,
                    'email': email,
                    'company': company,
                    'role': role
                })
                
                # Create email message
                msg = MIMEMultipart('alternative')
                msg['Subject'] = subject
                msg['From'] = f"{FROM_NAME} <{FROM_EMAIL}>"
                msg['To'] = email
                
                # Create HTML and plain text versions
                html_content = f"""
                <html>
                <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                    {personalized_content.replace(chr(10), '<br>')}
                    <br><br>
                    <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
                    <p style="font-size: 12px; color: #666;">
                        This email was sent to {email} because you signed up for the PitchPerfectAI waitlist.
                        <br>If you no longer wish to receive these emails, please reply with "UNSUBSCRIBE".
                    </p>
                </body>
                </html>
                """
                
                plain_content = f"""
                {personalized_content}
                
                ---
                This email was sent to {email} because you signed up for the PitchPerfectAI waitlist.
                If you no longer wish to receive these emails, please reply with "UNSUBSCRIBE".
                """
                
                # Attach parts
                msg.attach(MIMEText(plain_content, 'plain'))
                msg.attach(MIMEText(html_content, 'html'))
                
                # Send email
                server.send_message(msg)
                sent_count += 1
                
            except Exception as e:
                print(f"Failed to send email to {email}: {str(e)}")
                continue
        
        server.quit()
        
    except Exception as e:
        print(f"SMTP connection error: {str(e)}")
        raise e
    
    return sent_count

def personalize_email_content(content, variables):
    """Replace variables in email content with actual values"""
    personalized = content
    for key, value in variables.items():
        personalized = personalized.replace(f"{{{{{key}}}}}", value or '')
    return personalized

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'admin_login'

# Database setup
def init_db():
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
    
    # Create waitlist users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS waitlist_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            name TEXT,
            company TEXT,
            role TEXT,
            signup_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'pending',
            notes TEXT
        )
    ''')
    
    # Create admin users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admin_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create email campaigns table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS email_campaigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT NOT NULL,
            content TEXT NOT NULL,
            recipients_count INTEGER DEFAULT 0,
            sent_at TIMESTAMP,
            created_by TEXT,
            status TEXT DEFAULT 'draft'
        )
    ''')
    
    # Create default admin user if none exists
    cursor.execute('SELECT COUNT(*) FROM admin_users')
    if cursor.fetchone()[0] == 0:
        password_hash = hashlib.sha256('admin123'.encode()).hexdigest()
        cursor.execute('INSERT INTO admin_users (username, password_hash) VALUES (?, ?)', 
                      ('admin', password_hash))
    
    conn.commit()
    conn.close()

class User:
    def __init__(self, id, username):
        self.id = id
        self.username = username
        self.is_authenticated = True
        self.is_active = True
        self.is_anonymous = False
    
    def get_id(self):
        return str(self.id)

@login_manager.user_loader
def load_user(user_id):
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT id, username FROM admin_users WHERE id = ?', (user_id,))
        user_data = cursor.fetchone()
        conn.close()
    
    if user_data:
        return User(user_data[0], user_data[1])
    return None

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

# Routes
@app.route('/')
def landing():
    return render_template('landing.html')

@app.route('/join', methods=['POST'])
def join_waitlist():
    email = request.form.get('email', '').strip().lower()
    name = request.form.get('name', '').strip()
    company = request.form.get('company', '').strip()
    role = request.form.get('role', '').strip()
    
    if not email:
        flash('Email is required', 'error')
        return redirect(url_for('landing'))
    
    try:
        with db_lock:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO waitlist_users (email, name, company, role) 
                VALUES (?, ?, ?, ?)
            ''', (email, name, company, role))
            conn.commit()
            conn.close()
        
        flash('Successfully joined the waitlist! We\'ll be in touch soon.', 'success')
    except sqlite3.IntegrityError:
        flash('This email is already on our waitlist!', 'info')
    except Exception as e:
        flash('An error occurred. Please try again.', 'error')
    
    return redirect(url_for('landing'))

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if username and password:
            password_hash = hashlib.sha256(password.encode()).hexdigest()
            
            with db_lock:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute('SELECT id, username FROM admin_users WHERE username = ? AND password_hash = ?', 
                              (username, password_hash))
                user_data = cursor.fetchone()
                conn.close()
            
            if user_data:
                user = User(user_data[0], user_data[1])
                login_user(user)
                return redirect(url_for('admin_dashboard'))
            else:
                flash('Invalid credentials', 'error')
    
    return render_template('admin_login.html')

@app.route('/admin/logout')
@login_required
def admin_logout():
    logout_user()
    return redirect(url_for('landing'))

@app.route('/admin')
@admin_required
def admin_dashboard():
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
    
    # Get waitlist statistics
    cursor.execute('SELECT COUNT(*) FROM waitlist_users')
    total_users = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM waitlist_users WHERE status = "pending"')
    pending_users = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM email_campaigns WHERE status = "sent"')
    sent_campaigns = cursor.fetchone()[0]
    
    # Get recent signups
    cursor.execute('''
        SELECT email, name, company, role, signup_date, status 
        FROM waitlist_users 
        ORDER BY signup_date DESC 
        LIMIT 10
    ''')
    recent_users_raw = cursor.fetchall()
    
    # Convert tuples to dictionaries for template access
    recent_users = []
    for user in recent_users_raw:
        recent_users.append({
            'email': user[0],
            'name': user[1],
            'company': user[2],
            'role': user[3],
            'signup_date': user[4],
            'status': user[5]
        })
    
    conn.close()
    
    return render_template('admin_dashboard.html', 
                         total_users=total_users,
                         pending_users=pending_users,
                         sent_campaigns=sent_campaigns,
                         recent_users=recent_users)

@app.route('/admin/users')
@admin_required
def admin_users():
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
    cursor.execute('''
        SELECT id, email, name, company, role, signup_date, status, notes 
        FROM waitlist_users 
        ORDER BY signup_date DESC
    ''')
    users = cursor.fetchall()
    conn.close()
    
    return render_template('admin_users.html', users=users)

@app.route('/admin/users/update', methods=['POST'])
@admin_required
def update_user_status():
    user_id = request.form.get('user_id')
    status = request.form.get('status')
    notes = request.form.get('notes', '')
    
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE waitlist_users SET status = ?, notes = ? WHERE id = ?', 
                      (status, notes, user_id))
        conn.commit()
        conn.close()
    
    flash('User updated successfully', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/emails')
@admin_required
def admin_emails():
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
    cursor.execute('''
        SELECT id, subject, recipients_count, sent_at, created_by, status 
        FROM email_campaigns 
        ORDER BY id DESC
    ''')
    campaigns = cursor.fetchall()
    conn.close()
    
    return render_template('admin_emails.html', campaigns=campaigns)

@app.route('/admin/emails/new', methods=['GET', 'POST'])
@admin_required
def new_email():
    if request.method == 'POST':
        subject = request.form.get('subject')
        content = request.form.get('content')
        action = request.form.get('action')
        
        if not subject or not content:
            flash('Subject and content are required', 'error')
            return render_template('new_email.html')
        
        with db_lock:
            conn = get_db_connection()
            cursor = conn.cursor()
        
        if action == 'save_draft':
            cursor.execute('''
                INSERT INTO email_campaigns (subject, content, created_by, status) 
                VALUES (?, ?, ?, 'draft')
            ''', (subject, content, current_user.username))
            flash('Email saved as draft', 'success')
        
        elif action == 'send_now':
            # Get all pending users with more details for personalization
            cursor.execute('SELECT email, name, company, role FROM waitlist_users WHERE status = "pending"')
            recipients = cursor.fetchall()
            
            if recipients:
                # Save campaign
                cursor.execute('''
                    INSERT INTO email_campaigns (subject, content, recipients_count, sent_at, created_by, status) 
                    VALUES (?, ?, ?, ?, ?, 'sent')
                ''', (subject, content, len(recipients), datetime.now(), current_user.username))
                
                # Send actual emails
                try:
                    sent_count = send_email_campaign(subject, content, recipients)
                    flash(f'Email sent to {sent_count} recipients', 'success')
                    
                    # Update user status to 'contacted' after successful email
                    recipient_emails = [r[0] for r in recipients]
                    placeholders = ','.join(['?' for _ in recipient_emails])
                    cursor.execute(f'UPDATE waitlist_users SET status = "contacted" WHERE email IN ({placeholders})', recipient_emails)
                    
                except Exception as e:
                    flash(f'Error sending emails: {str(e)}', 'error')
                    # Update campaign status to failed
                    cursor.execute('UPDATE email_campaigns SET status = "failed" WHERE id = last_insert_rowid()')
            else:
                flash('No pending users to send email to', 'warning')
        
        conn.commit()
        conn.close()
        
        return redirect(url_for('admin_emails'))
    
    return render_template('new_email.html')

@app.route('/admin/export')
@admin_required
def export_users():
    from flask import Response
    import csv
    import io
    
    conn = sqlite3.connect('waitlist.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT email, name, company, role, signup_date, status, notes 
        FROM waitlist_users 
        ORDER BY signup_date DESC
    ''')
    users = cursor.fetchall()
    conn.close()
    
    # Create CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow(['Email', 'Name', 'Company', 'Role', 'Signup Date', 'Status', 'Notes'])
    
    # Write data
    for user in users:
        writer.writerow(user)
    
    # Create response
    csv_data = output.getvalue()
    output.close()
    
    response = Response(
        csv_data,
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=waitlist_users.csv'}
    )
    
    return response

@app.route('/admin/test-email', methods=['POST'])
@admin_required
def test_email():
    """Send a test email to verify SMTP configuration"""
    test_email_addr = request.form.get('test_email')
    
    if not test_email_addr:
        flash('Please provide a test email address', 'error')
        return redirect(url_for('admin_emails'))
    
    try:
        # Send test email
        test_recipients = [(test_email_addr, 'Test User', '', '')]
        subject = "PitchPerfectAI - Email Configuration Test"
        content = """Hello {{name}},

This is a test email to verify that the email configuration is working correctly.

If you receive this email, the SMTP settings are properly configured!

Best regards,
The PitchPerfectAI Team"""
        
        sent_count = send_email_campaign(subject, content, test_recipients)
        flash(f'Test email sent successfully to {test_email_addr}', 'success')
        
    except Exception as e:
        flash(f'Test email failed: {str(e)}', 'error')
    
    return redirect(url_for('admin_emails'))

@app.route('/admin/send-draft', methods=['POST'])
@admin_required
def send_draft_campaign():
    """Send a draft campaign to all pending users"""
    campaign_id = request.form.get('campaign_id')
    
    if not campaign_id:
        flash('Invalid campaign ID', 'error')
        return redirect(url_for('admin_emails'))
    
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            # Get campaign details
            cursor.execute('SELECT subject, content FROM email_campaigns WHERE id = ? AND status = "draft"', (campaign_id,))
            campaign = cursor.fetchone()
            
            if not campaign:
                flash('Campaign not found or already sent', 'error')
                return redirect(url_for('admin_emails'))
            
            subject, content = campaign
            
            # Get all pending users
            cursor.execute('SELECT email, name, company, role FROM waitlist_users WHERE status = "pending"')
            recipients = cursor.fetchall()
            
            if recipients:
                # Send emails
                sent_count = send_email_campaign(subject, content, recipients)
                
                # Update campaign status
                cursor.execute('''
                    UPDATE email_campaigns 
                    SET status = "sent", sent_at = ?, recipients_count = ? 
                    WHERE id = ?
                ''', (datetime.now(), sent_count, campaign_id))
                
                # Update user status to 'contacted'
                recipient_emails = [r[0] for r in recipients]
                placeholders = ','.join(['?' for _ in recipient_emails])
                cursor.execute(f'UPDATE waitlist_users SET status = "contacted" WHERE email IN ({placeholders})', recipient_emails)
                
                flash(f'Campaign sent to {sent_count} recipients', 'success')
            else:
                flash('No pending users to send email to', 'warning')
                
        except Exception as e:
            flash(f'Error sending campaign: {str(e)}', 'error')
        
        conn.commit()
        conn.close()
    
    return redirect(url_for('admin_emails'))

@app.route('/admin/view-campaign/<int:campaign_id>')
@admin_required
def view_campaign(campaign_id):
    """View campaign details"""
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT id, subject, content, recipients_count, sent_at, created_by, status FROM email_campaigns WHERE id = ?', (campaign_id,))
        campaign = cursor.fetchone()
        conn.close()
    
    if not campaign:
        flash('Campaign not found', 'error')
        return redirect(url_for('admin_emails'))
    
    campaign_data = {
        'id': campaign[0],
        'subject': campaign[1],
        'content': campaign[2],
        'recipients_count': campaign[3],
        'sent_at': campaign[4],
        'created_by': campaign[5],
        'status': campaign[6]
    }
    
    return render_template('view_campaign.html', campaign=campaign_data)

@app.route('/admin/delete-campaign/<int:campaign_id>', methods=['POST'])
@admin_required
def delete_campaign(campaign_id):
    """Delete a campaign"""
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('DELETE FROM email_campaigns WHERE id = ?', (campaign_id,))
            conn.commit()
            
            if cursor.rowcount > 0:
                flash('Campaign deleted successfully', 'success')
            else:
                flash('Campaign not found', 'error')
                
        except Exception as e:
            flash(f'Error deleting campaign: {str(e)}', 'error')
        
        conn.close()
    return redirect(url_for('admin_emails'))

@app.route('/api/stats')
@admin_required
def api_stats():
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get signups by day for the last 30 days
        cursor.execute('''
            SELECT DATE(signup_date) as date, COUNT(*) as count 
            FROM waitlist_users 
            WHERE signup_date >= date('now', '-30 days')
            GROUP BY DATE(signup_date)
            ORDER BY date
        ''')
        daily_signups = cursor.fetchall()
        
        conn.close()
    
    return jsonify({
        'daily_signups': [{'date': row[0], 'count': row[1]} for row in daily_signups]
    })

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5001)
