# PitchPerfectAI Waitlist

A beautiful waitlist application for PitchPerfectAI - the platform that transforms GitHub repositories into compelling pitch decks.

## Features

### Public Landing Page
- Modern, responsive design with gradient backgrounds
- Feature showcase highlighting AI-powered analysis
- Waitlist signup form with optional company/role fields
- Mobile-optimized user experience

### Admin Dashboard
- **User Management**: View, edit, and manage waitlist signups
- **Email Campaigns**: Create, draft, and send targeted emails
- **Analytics**: Track signups, user status, and campaign performance
- **Export Functionality**: Download user data as CSV

### Email System
- Rich text email composer with formatting tools
- Variable substitution ({{name}}, {{email}}, {{company}})
- Pre-built templates for common campaigns
- Draft and send functionality

## Quick Start

1. **Install Dependencies**
   ```bash
   cd pitchperfect-waitlist
   pip install -r requirements.txt
   ```

2. **Run the Application**
   ```bash
   python app.py
   ```

3. **Access the Application**
   - Landing page: http://localhost:5001
   - Admin login: http://localhost:5001/admin/login
   - Default credentials: `admin` / `admin123`

## Database

The application uses SQLite for simplicity. The database is automatically created on first run with the following tables:

- `waitlist_users`: Stores user signups with email, name, company, role, status
- `admin_users`: Admin authentication (default admin user created automatically)
- `email_campaigns`: Email campaign history and drafts

## Admin Features

### User Management
- View all waitlist signups in a sortable table
- Edit user status (pending, contacted, invited, rejected)
- Add notes to user records
- Export user data as CSV

### Email Campaigns
- Create rich text emails with formatting
- Use variables for personalization
- Save drafts or send immediately
- Track sent campaigns and recipient counts

### Templates
- **Welcome Email**: Thank new signups and set expectations
- **Progress Update**: Share development milestones
- **Launch Invitation**: Invite users to try the product

## Customization

### Branding
- Update colors in `templates/base.html` (Tailwind CSS configuration)
- Modify logo and company name throughout templates
- Customize email templates in `templates/new_email.html`

### Email Integration
To enable actual email sending, integrate with an email service:
- SMTP configuration in `app.py`
- Email service APIs (SendGrid, Mailgun, etc.)
- Update the `handle_successful_payment` function

## Security Notes

- Change default admin credentials in production
- Use environment variables for sensitive configuration
- Implement proper session management for production use
- Add CSRF protection for forms

## Deployment

### Vercel Deployment

This application is configured for Vercel deployment with serverless functions:

1. **Environment Variables** (set in Vercel dashboard):
   ```
   SMTP_SERVER=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USERNAME=your-email@gmail.com
   SMTP_PASSWORD=your-app-password
   FROM_EMAIL=noreply@pitchperfectai.com
   FROM_NAME=PitchPerfectAI Team
   ```

2. **Deploy to Vercel**:
   ```bash
   npm i -g vercel
   vercel --prod
   ```

### Other Platforms
Also compatible with:
- Heroku
- DigitalOcean App Platform
- AWS Elastic Beanstalk

Remember to:
1. Set up a production database (consider PostgreSQL for production)
2. Configure email service credentials
3. Update admin credentials
4. Set proper environment variables
