"""
Authentication module for NiceGUI-based Referee Mentor System
"""

import hashlib
import hmac
import logging
import secrets
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from nicegui import ui, app
from fastapi import Request
from password_validator import PasswordValidator

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import RefereeDbCockroach
from sendemail import SendMailSimple

# Password validation schema
schema = PasswordValidator()
schema.min(10).max(100).has().uppercase().has().lowercase().has().digits().has().symbols().has().no().spaces()
PASSWORD_REQUIREMENTS = "Minimum 10 characters. At least one uppercase letter, one lowercase letter, one digit, and one special character. No spaces."


class AuthManager:
    """Handles user authentication and session management"""

    def __init__(self):
        self.db = RefereeDbCockroach()

    def hash_password(self, password: str, salt: str = None) -> Tuple[str, str]:
        """Hash a password with salt"""
        if salt is None:
            salt = secrets.token_hex(16)

        password_hash = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt.encode('utf-8'),
            100000
        )
        return password_hash.hex(), salt

    def verify_password(self, password: str, hashed_password: str, salt: str) -> bool:
        """Verify a password against its hash"""
        password_hash, _ = self.hash_password(password, salt)
        return hmac.compare_digest(password_hash, hashed_password)

    def authenticate_user(self, username: str, password: str) -> bool:
        """Authenticate a user with username and password"""
        user = self.db.getUserByUsername(username)
        if user and self.verify_password(password, user['password_hash'], user['salt']):
            # Store in app storage
            app.storage.user['authenticated'] = True
            app.storage.user['username'] = username
            app.storage.user['user_role'] = user['role']
            app.storage.user['user_id'] = user['id']
            app.storage.user['email'] = user['email']

            self.db.updateLastLogin(username)
            return True
        return False

    def logout(self):
        """Logout the current user"""
        app.storage.user.clear()
        ui.navigate.to('/login')

    def is_authenticated(self) -> bool:
        """Check if user is authenticated"""
        return app.storage.user.get('authenticated', False)

    def get_current_user(self) -> Optional[str]:
        """Get the current authenticated username"""
        return app.storage.user.get('username')

    def get_user_role(self) -> Optional[str]:
        """Get the current user's role"""
        return app.storage.user.get('user_role')

    def is_admin(self) -> bool:
        """Check if current user is an admin"""
        return app.storage.user.get('user_role') == 'admin'

    def create_user(self, username: str, password: str, email: str, role: str = 'user') -> Tuple[bool, str]:
        """Create a new user account"""
        if self.db.userExists(username):
            return False, "Username already exists"

        if self.db.emailExists(email):
            return False, "Email already registered"

        password_hash, salt = self.hash_password(password)

        try:
            self.db.createUser(username, password_hash, salt, email, role)
            return True, "User created successfully"
        except Exception as e:
            return False, f"Error creating user: {str(e)}"

    def change_password(self, username: str, old_password: str, new_password: str) -> Tuple[bool, str]:
        """Change user's password"""
        user = self.db.getUserByUsername(username)
        if not user:
            return False, "User not found"

        if not self.verify_password(old_password, user['password_hash'], user['salt']):
            return False, "Current password is incorrect"

        new_hash, new_salt = self.hash_password(new_password)

        try:
            self.db.updateUserPassword(username, new_hash, new_salt)
            return True, "Password changed successfully"
        except Exception as e:
            return False, f"Error changing password: {str(e)}"

    def generate_reset_token(self) -> str:
        """Generate a secure password reset token"""
        return secrets.token_urlsafe(32)

    def request_password_reset(self, email: str) -> Tuple[bool, str]:
        """Request a password reset for the given email"""
        user = self.db.getUserByEmail(email)

        if not user:
            return True, "If the email exists in our system, a password reset link will be sent."

        try:
            token = self.generate_reset_token()
            expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

            self.db.createPasswordResetToken(user['id'], token, expires_at)

            # Send email
            email_client = SendMailSimple()
            email_client.send(
                email,
                "Referee Mentor System Password Reset",
                f"""<h3>This is a message from the Referee Mentor Website.</h3>
                <table>
                    <tr><td>If you did not request a password reset, you can safely ignore this email.</td></tr>
                    <tr><td><b>Use the following token to reset your password:</b></td></tr>
                    <tr><td style="text-align: center; vertical-align: middle;">{token}</td></tr>
                </table>
                """
            )

            return True, "Password reset requested. Check your email for the reset link."
        except Exception as e:
            return False, f"Error requesting password reset: {str(e)}"

    def reset_password_with_token(self, token: str, new_password: str, email: str) -> Tuple[bool, str]:
        """Reset password using a valid token"""
        token_data = self.db.getPasswordResetToken(token, email)

        if not token_data:
            return False, "Invalid or expired reset token"

        try:
            new_hash, new_salt = self.hash_password(new_password)
            self.db.updateUserPassword(token_data['username'], new_hash, new_salt)
            self.db.usePasswordResetToken(token)
            self.db.cleanupExpiredTokens()

            return True, "Password reset successfully"
        except Exception as e:
            return False, f"Error resetting password: {str(e)}"

    def log_current_user(self, request=None):
        """
        Log the current user's visit with additional metadata.

        Args:
            request: FastAPI Request object (optional) - if provided, extracts IP and user agent
        """
        role = app.storage.user.get('user_role')
        username = app.storage.user.get('username')
        email = app.storage.user.get('email')
        if username and email:
            # Extract IP address and user agent from request if available
            ip_address = None
            user_agent = None

            if request:
                # Get IP address - handle proxy headers (X-Forwarded-For, X-Real-IP)
                forwarded_for = request.headers.get('X-Forwarded-For')
                if forwarded_for:
                    # X-Forwarded-For can contain multiple IPs, take the first one
                    ip_address = forwarded_for.split(',')[0].strip()
                else:
                    # Fall back to X-Real-IP header if present
                    ip_address = request.headers.get('X-Real-IP') or (request.client.host if request.client else None)

                # Get user agent
                user_agent = request.headers.get('User-Agent')

            self.db.addVisitor(email, username, role, ip_address, user_agent)


def require_auth(auth_manager: AuthManager):
    """Require authentication - redirect to login if not authenticated"""
    if not auth_manager.is_authenticated():
        ui.navigate.to('/login')
        return False
    return True


@ui.page('/login')
def login_page():
    """Login page"""
    auth_manager = AuthManager()


    # Apply dark mode via head HTML script that runs on page load
    ui.add_head_html('''
        <script>
            (function() {
                document.body.classList.add("dark");
                document.documentElement.classList.add("dark");
            })();
        </script>
    ''')

    ui.add_head_html('''
    <style>
        body.dark {
            background-color: #121212 !important;
        }
        html.dark {
            background-color: #121212 !important;
        }
        .login-container {
            max-width: 400px;
            margin: 100px auto;
            padding: 40px;
        }
    </style>
    ''')

    with ui.card().classes('login-container'):
        ui.label('🏆 Referee Mentor System').classes('text-2xl font-bold text-center w-full mb-2')
        ui.label('Please log in to continue').classes('text-gray-600 text-center w-full mb-6')

        username_input = ui.input('Username', placeholder='Enter your username').classes('w-full')
        password_input = ui.input('Password', placeholder='Enter your password', password=True).classes('w-full')

        message_area = ui.column().classes('w-full')

        def do_login():
            message_area.clear()
            if not username_input.value or not password_input.value:
                with message_area:
                    ui.label('Please enter both username and password').classes('text-red-500')
                return

            # Get request from NiceGUI context when login happens
            request = None
            try:
                from nicegui import context
                if hasattr(context, 'client') and context.client and hasattr(context.client, 'request'):
                    request = context.client.request
            except Exception as e:
                logging.debug(f"Could not get request from context: {e}")

            if auth_manager.authenticate_user(username_input.value, password_input.value):
                auth_manager.log_current_user(request)
                ip_info = request.client.host if request and request.client else 'unknown'
                logging.info(f"User {username_input.value} logged in from IP {ip_info}, navigating to /")

                # Navigate to main page (which will show its own loading spinner while data loads)
                ui.navigate.to('/')
            else:
                with message_area:
                    ui.label('Invalid username or password').classes('text-red-500')

        ui.button('Login', on_click=do_login).classes('w-full mt-4').props('color=primary')

        ui.button('Forgot Password?', on_click=lambda: ui.navigate.to('/forgot-password')).classes('w-full mt-2').props('flat')


@ui.page('/forgot-password')
def forgot_password_page():
    """Forgot password page"""
    auth_manager = AuthManager()

    with ui.card().classes('login-container'):
        ui.label('🏆 Referee Mentor System').classes('text-2xl font-bold text-center w-full mb-2')
        ui.label('Reset Your Password').classes('text-gray-600 text-center w-full mb-6')

        email_input = ui.input('Email Address', placeholder='Enter your email').classes('w-full')

        message_area = ui.column().classes('w-full')

        def do_reset():
            message_area.clear()
            if not email_input.value:
                with message_area:
                    ui.label('Please enter your email address').classes('text-red-500')
                return

            success, message = auth_manager.request_password_reset(email_input.value)
            with message_area:
                if success:
                    ui.label(message).classes('text-green-500')
                    app.storage.user['reset_email'] = email_input.value
                else:
                    ui.label(message).classes('text-red-500')

        with ui.row().classes('w-full gap-2 mt-4'):
            ui.button('Send Reset Link', on_click=do_reset).props('color=primary')
            ui.button('Cancel', on_click=lambda: ui.navigate.to('/login')).props('color=grey')

        ui.button('Have a token? Reset password', on_click=lambda: ui.navigate.to('/reset-password')).classes('w-full mt-4').props('flat')


@ui.page('/reset-password')
def reset_password_page():
    """Reset password page"""
    auth_manager = AuthManager()

    with ui.card().classes('login-container'):
        ui.label('🏆 Referee Mentor System').classes('text-2xl font-bold text-center w-full mb-2')
        ui.label('Enter New Password').classes('text-gray-600 text-center w-full mb-6')

        email_input = ui.input('Email', value=app.storage.user.get('reset_email', '')).classes('w-full')
        token_input = ui.input('Reset Token', placeholder='Enter your reset token').classes('w-full')
        password_input = ui.input('New Password', placeholder='Enter new password', password=True).classes('w-full')
        confirm_input = ui.input('Confirm Password', placeholder='Confirm new password', password=True).classes('w-full')

        message_area = ui.column().classes('w-full')

        def do_reset():
            message_area.clear()

            if not all([email_input.value, token_input.value, password_input.value, confirm_input.value]):
                with message_area:
                    ui.label('All fields are required').classes('text-red-500')
                return

            if not schema.validate(password_input.value):
                with message_area:
                    ui.label(f'Password requirements: {PASSWORD_REQUIREMENTS}').classes('text-red-500')
                return

            if password_input.value != confirm_input.value:
                with message_area:
                    ui.label('Passwords do not match').classes('text-red-500')
                return

            success, message = auth_manager.reset_password_with_token(
                token_input.value,
                password_input.value,
                email_input.value
            )

            with message_area:
                if success:
                    ui.label(message).classes('text-green-500')
                    ui.label('You can now log in with your new password.').classes('text-gray-600')
                    # Clear reset email from storage
                    if 'reset_email' in app.storage.user:
                        del app.storage.user['reset_email']
                    # Redirect to login after 2 seconds
                    ui.timer(2.0, lambda: ui.navigate.to('/login'), once=True)
                else:
                    ui.label(message).classes('text-red-500')

        with ui.row().classes('w-full gap-2 mt-4'):
            ui.button('Reset Password', on_click=do_reset).props('color=primary')
            ui.button('Cancel', on_click=lambda: ui.navigate.to('/login')).props('color=grey')


@ui.page('/change-password')
def change_password_page():
    """Change password page for authenticated users"""
    auth_manager = AuthManager()

    if not auth_manager.is_authenticated():
        ui.navigate.to('/login')
        return

    ui.add_head_html('''
    <style>
        .login-container {
            max-width: 400px;
            margin: 100px auto;
            padding: 40px;
        }
    </style>
    ''')

    with ui.card().classes('login-container'):
        ui.label('🏆 Referee Mentor System').classes('text-2xl font-bold text-center w-full mb-2')
        ui.label('Change Password').classes('text-gray-600 text-center w-full mb-6')

        current_password = ui.input('Current Password', placeholder='Enter current password', password=True).classes('w-full')
        new_password = ui.input('New Password', placeholder='Enter new password', password=True).classes('w-full')
        confirm_password = ui.input('Confirm Password', placeholder='Confirm new password', password=True).classes('w-full')

        message_area = ui.column().classes('w-full')

        def do_change():
            message_area.clear()

            if not all([current_password.value, new_password.value, confirm_password.value]):
                with message_area:
                    ui.label('All fields are required').classes('text-red-500')
                return

            if not schema.validate(new_password.value):
                with message_area:
                    ui.label(f'Password requirements: {PASSWORD_REQUIREMENTS}').classes('text-red-500')
                return

            if new_password.value != confirm_password.value:
                with message_area:
                    ui.label('Passwords do not match').classes('text-red-500')
                return

            success, message = auth_manager.change_password(
                auth_manager.get_current_user(),
                current_password.value,
                new_password.value
            )

            with message_area:
                if success:
                    # ui.label(message).classes('text-green-500')
                    # ui.label('Please log in again with your new password.').classes('text-gray-600')
                    ui.notify(message + ' Please log in again with your new password.')
                    # Log out after password change
                    ui.timer(2.0, lambda: auth_manager.logout(), once=True)
                else:
                    ui.label(message).classes('text-red-500')

        with ui.row().classes('w-full gap-2 mt-4'):
            ui.button('Change Password', on_click=do_change).props('color=primary')
            ui.button('Cancel', on_click=lambda: ui.navigate.to('/')).props('color=grey')


@ui.page('/admin/users')
def user_management_page():
    """User management page for admins"""
    auth_manager = AuthManager()

    if not auth_manager.is_authenticated() or not auth_manager.is_admin():
        ui.navigate.to('/')
        return

    with ui.header().classes('bg-blue-900 text-white'):
        ui.label('🏆 User Management').classes('text-2xl font-bold')
        ui.space()
        ui.button('Back to App', on_click=lambda: ui.navigate.to('/')).props('flat color=white')

    with ui.tabs() as tabs:
        create_tab = ui.tab('Create User')
        manage_tab = ui.tab('Manage Users')

    with ui.tab_panels(tabs, value=create_tab).classes('w-full'):
        with ui.tab_panel(create_tab):
            with ui.card().classes('max-w-md mx-auto p-6'):
                ui.label('Create New User').classes('text-xl font-bold mb-4')

                new_username = ui.input('Username').classes('w-full')
                new_email = ui.input('Email').classes('w-full')
                new_password = ui.input('Password', password=True).classes('w-full')
                confirm_password = ui.input('Confirm Password', password=True).classes('w-full')
                new_role = ui.select(['user', 'admin'], value='user', label='Role').classes('w-full')

                message_area = ui.column().classes('w-full')

                def create_user():
                    message_area.clear()

                    if not all([new_username.value, new_email.value, new_password.value, confirm_password.value]):
                        with message_area:
                            ui.label('All fields are required').classes('text-red-500')
                        return

                    if not schema.validate(new_password.value):
                        with message_area:
                            ui.label(f'Password requirements: {PASSWORD_REQUIREMENTS}').classes('text-red-500')
                        return

                    if new_password.value != confirm_password.value:
                        with message_area:
                            ui.label('Passwords do not match').classes('text-red-500')
                        return

                    success, message = auth_manager.create_user(
                        new_username.value,
                        new_password.value,
                        new_email.value,
                        new_role.value
                    )

                    with message_area:
                        if success:
                            ui.label(message).classes('text-green-500')
                            new_username.value = ''
                            new_email.value = ''
                            new_password.value = ''
                            confirm_password.value = ''
                        else:
                            ui.label(message).classes('text-red-500')

                ui.button('Create User', on_click=create_user).props('color=primary')

        with ui.tab_panel(manage_tab):
            with ui.card().classes('w-full p-6'):
                ui.label('Current Users').classes('text-xl font-bold mb-4')

                users = auth_manager.db.getAllUsers()

                if users:
                    columns = [
                        {'name': 'username', 'label': 'Username', 'field': 'username'},
                        {'name': 'email', 'label': 'Email', 'field': 'email'},
                        {'name': 'role', 'label': 'Role', 'field': 'role'},
                    ]
                    rows = [{'username': u['username'], 'email': u['email'], 'role': u['role']} for u in users]
                    ui.table(columns=columns, rows=rows).classes('w-full')
                else:
                    ui.label('No users found')

