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


def _format_timestamp(ts) -> str:
    """Format a timestamp for display in admin tables."""
    if ts is None:
        return 'Never'
    if hasattr(ts, 'strftime'):
        return ts.strftime('%Y-%m-%d %H:%M')
    return str(ts)


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

    def authenticate_user(self, username: str, password: str, organization_id: Optional[int] = None) -> bool:
        """Authenticate a user with username and password. If organization_id is given, user must belong to that organization."""
        user = self.db.getUserByUsername(username)
        if not user:
            logging.error(f"User {username} not found")
            return False
        if not self.verify_password(password, user['password_hash'], user['salt']):
            logging.error(f"User {username} failed to login with password")
            return False
        if organization_id is not None and not self.db.userBelongsToOrganization(user['id'], organization_id):
            logging.error(f"User {username} does not belong to organization {organization_id}")
            return False
        # Store in app storage
        app.storage.user['authenticated'] = True
        app.storage.user['username'] = username
        app.storage.user['user_role'] = user['role']
        app.storage.user['user_id'] = user['id']
        app.storage.user['email'] = user['email']
        app.storage.user['organization_id'] = organization_id
        if organization_id is not None:
            orgs = self.db.getOrganizations()
            org = next((o for o in orgs if o['id'] == organization_id), None)
            app.storage.user['organization_name'] = org['name'] if org else None
        else:
            app.storage.user['organization_name'] = None

        self.db.updateLastLogin(username)
        return True

    def logout(self):
        """Logout the current user"""
        try:
            app.storage.user.clear()
        except RuntimeError:
            pass
        ui.navigate.to('/login')

    def _storage_get(self, key: str, default=None):
        """Read session storage; returns default outside a browser request (e.g. background threads)."""
        try:
            return app.storage.user.get(key, default)
        except RuntimeError:
            return default

    def is_authenticated(self) -> bool:
        """Check if user is authenticated"""
        return bool(self._storage_get('authenticated', False))

    def get_current_user(self) -> Optional[str]:
        """Get the current authenticated username"""
        return self._storage_get('username')

    def get_user_role(self) -> Optional[str]:
        """Get the current user's role"""
        return self._storage_get('user_role')

    def get_current_organization_id(self) -> Optional[int]:
        """Get the current user's organization id (multi-tenant)"""
        return self._storage_get('organization_id')

    def get_current_organization_name(self) -> Optional[str]:
        """Get the current user's organization name (multi-tenant)"""
        return self._storage_get('organization_name')

    def get_organizations(self) -> list:
        """Get all organizations for the login dropdown (multi-tenant)"""
        return self.db.getOrganizations()

    def is_admin(self) -> bool:
        """Check if current user is an admin"""
        return self._storage_get('user_role') == 'admin'

    def create_user(
        self,
        username: str,
        password: str,
        email: str,
        role: str = 'user',
        organization_id: Optional[int] = None,
    ) -> Tuple[bool, str]:
        """Create a new user account and associate with an organization."""
        if organization_id is None:
            return False, "Organization is required"

        org = self.db.getOrganizationById(organization_id)
        if not org:
            return False, "Invalid organization"

        if self.db.userExists(username):
            return False, "Username already exists"

        if self.db.emailExists(email):
            return False, "Email already registered"

        password_hash, salt = self.hash_password(password)

        try:
            self.db.createUser(username, password_hash, salt, email, role)
            user = self.db.getUserByUsername(username)
            if user:
                self.db.addUserToOrganization(user['id'], organization_id)
            return True, f"User created successfully and added to {org['name']}"
        except Exception as e:
            return False, f"Error creating user: {str(e)}"

    def create_organization(self, name: str, slug: str = None) -> Tuple[bool, str]:
        return self.db.createOrganization(name, slug)

    def delete_organization(self, organization_id: int) -> Tuple[bool, str]:
        return self.db.deleteOrganization(organization_id)

    def add_user_to_organization(self, user_id: int, organization_id: int) -> Tuple[bool, str]:
        user = self.db.getUserById(user_id)
        if not user:
            return False, 'User not found'
        org = self.db.getOrganizationById(organization_id)
        if not org:
            return False, 'Organization not found'
        if self.db.userBelongsToOrganization(user_id, organization_id):
            return False, f"{user['username']} is already in {org['name']}"
        try:
            self.db.addUserToOrganization(user_id, organization_id)
            return True, f"Added {user['username']} to {org['name']}"
        except Exception as e:
            return False, f'Error adding user to organization: {e}'

    def remove_user_from_organization(self, user_id: int, organization_id: int) -> Tuple[bool, str]:
        return self.db.removeUserFromOrganization(user_id, organization_id)

    def update_user_role(self, user_id: int, role: str) -> Tuple[bool, str]:
        current_id = self._storage_get('user_id')
        if current_id is not None and int(current_id) == int(user_id) and role != 'admin':
            return False, 'You cannot remove your own admin role'
        return self.db.updateUserRole(user_id, role)

    def delete_user(self, user_id: int) -> Tuple[bool, str]:
        current_id = self._storage_get('user_id')
        if current_id is not None and int(current_id) == int(user_id):
            return False, 'You cannot delete your own account'
        return self.db.deleteUser(user_id)

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
            expires_at = datetime.now(timezone.utc) + timedelta(hours=4)

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


def render_app_header(title: str = 'Referee Mentor System') -> None:
    """Render the standard app header."""
    with ui.header().classes('bg-blue-900 text-white'):
        ui.label(f'🏆 {title}').classes('text-2xl font-bold')


def render_user_sidebar(auth_manager: AuthManager, *, show_back_to_app: bool = False) -> None:
    """Render the left drawer with user menu and admin links."""
    drawer_kwargs = {'top_corner': True, 'bottom_corner': True}
    if show_back_to_app:
        drawer_kwargs['value'] = True
    with ui.left_drawer(**drawer_kwargs).classes('p-4'):
        if show_back_to_app:
            ui.button('Back to App', on_click=lambda: ui.navigate.to('/')).classes('w-full mb-2').props('flat')
            ui.separator().classes('my-2')

        current_user = auth_manager.get_current_user()
        if current_user:
            ui.label('Logged in as:').classes('text-gray-600 text-sm')
            ui.label(f'{current_user}').classes('font-bold mb-2')
            user_role = auth_manager.get_user_role()
            if user_role:
                ui.label(f'Role: {user_role}').classes('text-gray-600 text-sm mb-2')
            org_name = auth_manager.get_current_organization_name()
            if org_name:
                ui.label(f'Organization: {org_name}').classes('text-gray-600 text-sm mb-4')
            elif auth_manager.get_current_organization_id() is not None:
                ui.label('Organization: (unknown)').classes('text-gray-600 text-sm mb-4')
            else:
                ui.label('Organization: not set').classes('text-gray-600 text-sm mb-4')

        ui.separator()

        ui.button('Change Password', on_click=lambda: ui.navigate.to('/change-password')).classes('w-full mt-4').props('flat')
        ui.button('Logout', on_click=lambda: auth_manager.logout()).classes('w-full mt-2').props('flat color=red')

        if auth_manager.is_admin():
            ui.separator().classes('my-4')
            ui.label('Admin Functions').classes('font-bold text-sm')
            ui.button('User Management', on_click=lambda: ui.navigate.to('/admin/users')).classes('w-full mt-2').props('flat')
            ui.button('User Activity', on_click=lambda: ui.navigate.to('/admin/user-activity')).classes('w-full mt-2').props('flat')
            ui.button('Organizations', on_click=lambda: ui.navigate.to('/admin/organizations')).classes('w-full mt-2').props('flat')

        ui.label('Version: ' + open('VERSION', 'r').read().strip()).classes('text-gray-600 text-right w-full mb-6')


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

    ui.add_head_html('<link rel="manifest" href="/static/manifest.json">')
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
        ui.label('Please log in to continue').classes('text-gray-300 text-center w-full mb-6')

        orgs = auth_manager.get_organizations()
        # NiceGUI select: dict keys = stored value, dict values = display label
        org_options = {o['id']: o['name'] for o in orgs}
        organization_select = ui.select(
            options=org_options,
            label='Organization',
            value=list(org_options.keys())[0] if org_options else None,
        ).classes('w-full')
        username_input = ui.input('Username', placeholder='Enter your username').classes('w-full')
        password_input = ui.input('Password', placeholder='Enter your password', password=True).classes('w-full')

        message_area = ui.column().classes('w-full')

        def do_login():
            message_area.clear()
            if not username_input.value or not password_input.value:
                with message_area:
                    ui.label('Please enter both username and password').classes('text-red-500')
                return

            org_id = organization_select.value if organization_select.value is not None else None

            # Get request from NiceGUI context when login happens
            request = None
            try:
                from nicegui import context
                if hasattr(context, 'client') and context.client and hasattr(context.client, 'request'):
                    request = context.client.request
            except Exception as e:
                logging.debug(f"Could not get request from context: {e}")

            if auth_manager.authenticate_user(username_input.value, password_input.value, organization_id=org_id):
                auth_manager.log_current_user(request)
                ip_info = request.client.host if request and request.client else 'unknown'
                logging.info(f"User {username_input.value} logged in from IP {ip_info}, navigating to /")

                # Navigate to main page (which will show its own loading spinner while data loads)
                ui.navigate.to('/')
            else:
                logging.error(f"User {username_input.value} failed to login using organization {org_id}")
                with message_area:
                    ui.label('Invalid username, password, or you do not have access to the selected organization.').classes('text-red-500')

        ui.button('Login', on_click=do_login).classes('w-full mt-4').props('color=primary')
        ui.button('Forgot Password?', on_click=lambda: ui.navigate.to('/forgot-password')).classes('w-full mt-2').props('flat')
        ui.button('Back to Home', on_click=lambda: ui.navigate.to('/')).classes('w-full mt-2').props('flat')
        ui.label('Version: ' + open('VERSION', 'r').read().strip()).classes('text-gray-600 text-right w-full mb-6')


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


@ui.page('/admin/organizations')
def organizations_page():
    """Organization management (admin only)."""
    auth_manager = AuthManager()

    if not auth_manager.is_authenticated() or not auth_manager.is_admin():
        ui.navigate.to('/')
        return

    ui.dark_mode(True)
    render_app_header()
    render_user_sidebar(auth_manager, show_back_to_app=True)

    with ui.card().classes('w-full p-6'):
        ui.label('Organizations').classes('text-xl font-bold mb-4')

        org_list_area = ui.column().classes('w-full mb-6')
        message_area = ui.column().classes('w-full mb-4')

        def render_org_list():
            org_list_area.clear()
            orgs = auth_manager.get_organizations()
            counts_by_org = {
                o['id']: auth_manager.db.getOrganizationDependencyCounts(o['id'])
                for o in orgs
            }

            with org_list_area:
                if not orgs:
                    ui.label('No organizations yet. Create one below.').classes('text-gray-400')
                    return

                with ui.row().classes('w-full font-bold text-sm text-gray-400 px-2 pb-2'):
                    ui.label('Name').classes('flex-[2]')
                    ui.label('Slug').classes('flex-1')
                    ui.label('Users').classes('w-16')
                    ui.label('Referees').classes('w-20')
                    ui.label('').classes('w-24')

                for org in orgs:
                    counts = counts_by_org.get(org['id'], {})

                    def make_delete_handler(org_id: int, org_name: str):
                        def confirm_delete():
                            with ui.dialog() as dialog, ui.card():
                                ui.label(f'Delete organization "{org_name}"?').classes('text-lg font-bold')
                                ui.label(
                                    'User memberships and game selections for this org will be removed. '
                                    'Deletion is blocked if the org still has referees or game details.'
                                ).classes('text-sm text-gray-400 mb-4')

                                with ui.row().classes('w-full justify-end gap-2'):
                                    ui.button('Cancel', on_click=dialog.close).props('flat')

                                    def do_delete(org_id=org_id):
                                        success, message = auth_manager.delete_organization(org_id)
                                        dialog.close()
                                        message_area.clear()
                                        with message_area:
                                            ui.label(message).classes('text-green-500' if success else 'text-red-500')
                                        if success:
                                            render_org_list()

                                    ui.button('Delete', on_click=do_delete).props('color=negative')

                            dialog.open()

                        return confirm_delete

                    with ui.row().classes('w-full items-center gap-2 py-2 border-b border-gray-700 px-2'):
                        ui.label(org['name']).classes('flex-[2]')
                        ui.label(org['slug'] or '—').classes('flex-1 text-gray-400')
                        ui.label(str(counts.get('users', 0))).classes('w-16')
                        ui.label(str(counts.get('referees', 0))).classes('w-20')
                        ui.button('Delete', on_click=make_delete_handler(org['id'], org['name'])).props(
                            'flat dense color=negative'
                        ).classes('w-24')

        render_org_list()

        ui.separator().classes('my-4')
        ui.label('Add Organization').classes('text-lg font-bold mb-2')

        new_name = ui.input('Organization name').classes('w-full max-w-md')
        new_slug = ui.input('Slug (optional)').classes('w-full max-w-md')
        new_slug.props('placeholder="auto-generated from name if blank"')

        def add_organization():
            message_area.clear()
            success, message = auth_manager.create_organization(new_name.value, new_slug.value or None)
            with message_area:
                ui.label(message).classes('text-green-500' if success else 'text-red-500')
            if success:
                new_name.value = ''
                new_slug.value = ''
                render_org_list()

        ui.button('Create Organization', on_click=add_organization).props('color=primary')


@ui.page('/admin/users')
def user_management_page():
    """User management page for admins"""
    auth_manager = AuthManager()

    if not auth_manager.is_authenticated() or not auth_manager.is_admin():
        ui.navigate.to('/')
        return

    ui.dark_mode(True)
    render_app_header()
    render_user_sidebar(auth_manager, show_back_to_app=True)

    ui.label('User Management').classes('text-xl font-bold px-4 pt-4')

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

                orgs = auth_manager.get_organizations()
                org_options = {o['id']: o['name'] for o in orgs}
                new_org = ui.select(
                    options=org_options,
                    label='Organization',
                    value=next(iter(org_options)) if org_options else None,
                ).classes('w-full')
                if not org_options:
                    new_org.disable()
                    ui.label('Create an organization first (Admin → Organizations).').classes('text-orange-400 text-sm')

                message_area = ui.column().classes('w-full')

                def create_user():
                    message_area.clear()

                    if not all([new_username.value, new_email.value, new_password.value, confirm_password.value]):
                        with message_area:
                            ui.label('All fields are required').classes('text-red-500')
                        return

                    if new_org.value is None:
                        with message_area:
                            ui.label('Organization is required').classes('text-red-500')
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
                        new_role.value,
                        organization_id=new_org.value,
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

                orgs = auth_manager.get_organizations()
                org_options = {o['id']: o['name'] for o in orgs}
                org_select = ui.select(
                    options=org_options,
                    label='Filter by organization',
                    value=None,
                ).classes('w-full mb-4')
                org_select.props('clearable')

                manage_message = ui.column().classes('w-full mb-2')
                users_area = ui.column().classes('w-full')
                with users_area:
                    ui.label('Select an organization to view its users.').classes('text-gray-400')

                def open_edit_user_dialog(user: dict, filter_org_id):
                    user_orgs = auth_manager.db.getOrganizationsForUser(user['id'])
                    all_orgs = auth_manager.get_organizations()
                    member_ids = {o['id'] for o in user_orgs}
                    addable = {o['id']: o['name'] for o in all_orgs if o['id'] not in member_ids}

                    with ui.dialog() as dialog, ui.card().classes('w-full max-w-lg p-4'):
                        ui.label(f"Edit user: {user['username']}").classes('text-xl font-bold mb-1')
                        ui.label(user['email']).classes('text-sm text-gray-400 mb-4')

                        edit_message = ui.column().classes('w-full mb-2')
                        membership_area = ui.column().classes('w-full mb-4')

                        role_select = ui.select(
                            ['user', 'admin'],
                            value=user['role'],
                            label='Role',
                        ).classes('w-full mb-4')

                        def refresh_memberships():
                            membership_area.clear()
                            current_orgs = auth_manager.db.getOrganizationsForUser(user['id'])
                            with membership_area:
                                ui.label('Organizations').classes('font-semibold mb-2')
                                if not current_orgs:
                                    ui.label('Not a member of any organization.').classes('text-gray-400 text-sm')
                                for org in current_orgs:
                                    with ui.row().classes('w-full items-center justify-between py-1'):
                                        ui.label(org['name'])

                                        def make_remove(org_id: int, org_name: str):
                                            def do_remove():
                                                edit_message.clear()
                                                success, message = auth_manager.remove_user_from_organization(
                                                    user['id'], org_id
                                                )
                                                with edit_message:
                                                    ui.label(message).classes(
                                                        'text-green-500' if success else 'text-red-500'
                                                    )
                                                if success:
                                                    refresh_memberships()
                                                    refresh_add_options()
                                                    render_users_for_org()
                                            return do_remove

                                        ui.button(
                                            'Remove',
                                            on_click=make_remove(org['id'], org['name']),
                                        ).props('flat dense color=negative')

                        def refresh_add_options():
                            current_ids = {
                                o['id'] for o in auth_manager.db.getOrganizationsForUser(user['id'])
                            }
                            add_org_select.options = {
                                o['id']: o['name']
                                for o in auth_manager.get_organizations()
                                if o['id'] not in current_ids
                            }
                            add_org_select.value = None
                            add_org_select.update()

                        refresh_memberships()

                        ui.label('Add to organization').classes('font-semibold mb-2')
                        add_org_select = ui.select(
                            options=addable,
                            label='Organization',
                            value=None,
                        ).classes('w-full mb-2')
                        add_org_select.props('clearable')

                        def do_add_org():
                            edit_message.clear()
                            if add_org_select.value is None:
                                with edit_message:
                                    ui.label('Select an organization to add').classes('text-red-500')
                                return
                            success, message = auth_manager.add_user_to_organization(
                                user['id'], add_org_select.value
                            )
                            with edit_message:
                                ui.label(message).classes('text-green-500' if success else 'text-red-500')
                            if success:
                                refresh_memberships()
                                refresh_add_options()
                                render_users_for_org()

                        ui.button('Add to organization', on_click=do_add_org).props('color=primary').classes('mb-4')

                        def do_save_role():
                            edit_message.clear()
                            success, message = auth_manager.update_user_role(user['id'], role_select.value)
                            with edit_message:
                                ui.label(message).classes('text-green-500' if success else 'text-red-500')
                            if success:
                                user['role'] = role_select.value
                                render_users_for_org()

                        with ui.row().classes('w-full justify-end gap-2 mt-2'):
                            ui.button('Save role', on_click=do_save_role).props('color=primary')
                            ui.button('Close', on_click=dialog.close).props('flat')

                    dialog.open()

                def open_delete_user_dialog(user: dict):
                    with ui.dialog() as dialog, ui.card().classes('p-4'):
                        ui.label(f'Delete user "{user["username"]}"?').classes('text-lg font-bold')
                        ui.label(
                            'This permanently deletes the account and organization memberships. '
                            'It may fail if the user still has mentor sessions or game selections.'
                        ).classes('text-sm text-gray-400 mb-4')

                        with ui.row().classes('w-full justify-end gap-2'):
                            ui.button('Cancel', on_click=dialog.close).props('flat')

                            def do_delete():
                                manage_message.clear()
                                success, message = auth_manager.delete_user(user['id'])
                                dialog.close()
                                with manage_message:
                                    ui.label(message).classes('text-green-500' if success else 'text-red-500')
                                if success:
                                    render_users_for_org()

                            ui.button('Delete', on_click=do_delete).props('color=negative')

                    dialog.open()

                def render_users_for_org():
                    users_area.clear()
                    org_id = org_select.value
                    with users_area:
                        if org_id is None:
                            ui.label('Select an organization to view its users.').classes('text-gray-400')
                            return

                        users = auth_manager.db.getUsersByOrganization(org_id)
                        if not users:
                            ui.label('No users found in this organization.')
                            return

                        with ui.row().classes('w-full font-bold text-sm text-gray-400 px-2 pb-2'):
                            ui.label('Username').classes('flex-1')
                            ui.label('Email').classes('flex-[2]')
                            ui.label('Role').classes('w-20')
                            ui.label('').classes('w-40')

                        for user in users:
                            with ui.row().classes(
                                'w-full items-center gap-2 py-2 border-b border-gray-700 px-2'
                            ):
                                ui.label(user['username']).classes('flex-1')
                                ui.label(user['email']).classes('flex-[2] text-gray-300')
                                ui.label(user['role']).classes('w-20')
                                with ui.row().classes('w-40 gap-1 justify-end'):
                                    ui.button(
                                        'Edit',
                                        on_click=lambda u=user: open_edit_user_dialog(u, org_id),
                                    ).props('flat dense color=primary')
                                    ui.button(
                                        'Delete',
                                        on_click=lambda u=user: open_delete_user_dialog(u),
                                    ).props('flat dense color=negative')

                org_select.on_value_change(lambda: render_users_for_org())


@ui.page('/admin/user-activity')
def user_activity_page():
    """Recent login activity for users in a selected organization (admin only)."""
    auth_manager = AuthManager()

    if not auth_manager.is_authenticated() or not auth_manager.is_admin():
        ui.navigate.to('/')
        return

    ui.dark_mode(True)
    render_app_header()
    render_user_sidebar(auth_manager, show_back_to_app=True)

    with ui.card().classes('w-full p-6'):
        ui.label('User Activity').classes('text-xl font-bold mb-4')

        orgs = auth_manager.get_organizations()
        org_options = {o['id']: o['name'] for o in orgs}
        org_select = ui.select(
            options=org_options,
            label='Organization',
            value=None,
        ).classes('w-full mb-4')
        org_select.props('clearable')

        activity_area = ui.column().classes('w-full')
        with activity_area:
            ui.label('Select an organization to view user activity.').classes('text-gray-400')

        def render_activity_for_org():
            activity_area.clear()
            org_id = org_select.value
            with activity_area:
                if org_id is None:
                    ui.label('Select an organization to view user activity.').classes('text-gray-400')
                    return

                with ui.tabs() as tabs:
                    summary_tab = ui.tab('Last Login by User')
                    history_tab = ui.tab('Login History')

                with ui.tab_panels(tabs, value=summary_tab).classes('w-full'):
                    with ui.tab_panel(summary_tab):
                        users = auth_manager.db.getUsersLastLoginByOrganization(org_id)
                        if users:
                            columns = [
                                {'name': 'username', 'label': 'Username', 'field': 'username', 'align': 'left'},
                                {'name': 'email', 'label': 'Email', 'field': 'email', 'align': 'left'},
                                {'name': 'role', 'label': 'Role', 'field': 'role', 'align': 'left'},
                                {'name': 'last_login', 'label': 'Last Login', 'field': 'last_login', 'align': 'left'},
                            ]
                            rows = [
                                {
                                    'username': u['username'],
                                    'email': u['email'],
                                    'role': u['role'],
                                    'last_login': _format_timestamp(u['last_login']),
                                }
                                for u in users
                            ]
                            ui.table(columns=columns, rows=rows, row_key='username').classes('w-full')
                        else:
                            ui.label('No users found in this organization.')

                    with ui.tab_panel(history_tab):
                        logins = auth_manager.db.getRecentLoginsByOrganization(org_id)
                        if logins:
                            columns = [
                                {'name': 'login_time', 'label': 'Login Time', 'field': 'login_time', 'align': 'left'},
                                {'name': 'username', 'label': 'Username', 'field': 'username', 'align': 'left'},
                                {'name': 'email', 'label': 'Email', 'field': 'email', 'align': 'left'},
                                {'name': 'role', 'label': 'Role', 'field': 'role', 'align': 'left'},
                                {'name': 'ip_address', 'label': 'IP Address', 'field': 'ip_address', 'align': 'left'},
                            ]
                            rows = [
                                {
                                    'id': i,
                                    'login_time': _format_timestamp(entry['login_time']),
                                    'username': entry['username'],
                                    'email': entry['email'],
                                    'role': entry['role'],
                                    'ip_address': entry['ip_address'],
                                }
                                for i, entry in enumerate(logins)
                            ]
                            ui.table(columns=columns, rows=rows, row_key='id').classes('w-full')
                        else:
                            ui.label('No login history recorded for this organization.')

        org_select.on_value_change(lambda: render_activity_for_org())

