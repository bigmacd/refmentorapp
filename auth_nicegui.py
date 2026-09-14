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
from urllib.parse import urlencode

from nicegui import ui, app
from fastapi import Request
from password_validator import PasswordValidator

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from avatars import (
    MAX_UPLOAD_BYTES,
    avatar_data_url,
    delete_avatar,
    has_avatar,
    save_avatar,
)
from database import RefereeDbCockroach
from sendemail import SendMailSimple

# Password validation schema
schema = PasswordValidator()
schema.min(10).max(100).has().uppercase().has().lowercase().has().digits().has().symbols().has().no().spaces()
PASSWORD_REQUIREMENTS = "Minimum 10 characters. At least one uppercase letter, one lowercase letter, one digit, and one special character. No spaces."

RESET_REQUEST_SUCCESS_MESSAGE = (
    "If that email is in our system, you'll receive reset instructions shortly. "
    "Check your email for a reset link."
)
PASSWORD_RESET_TOKEN_TTL = timedelta(minutes=15)
APP_HOME = '/app'
HELP_PATH = '/help'
DARK_MODE_STORAGE_KEY = 'dark_mode'
DEFAULT_DARK_MODE = True
_USER_GUIDE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'docs', 'user-guide.md')
_USER_GUIDE_IMAGE_PREFIX = '](user-guide/images/'
_USER_GUIDE_IMAGE_URL = '](/guide-images/'


def resolve_app_base_url(request: Optional[Request] = None) -> str:
    """Public site origin for links in emails (no trailing slash).

    Prefers the current request host (so custom domains / staging match what the
    user sees), then APP_BASE_URL, then a local-dev default.
    """
    if request is not None:
        proto = request.headers.get('x-forwarded-proto') or request.url.scheme
        host = request.headers.get('x-forwarded-host') or request.headers.get('host') or request.url.netloc
        if host:
            return f'{proto}://{host}'.rstrip('/')
    env_url = (os.environ.get('APP_BASE_URL') or '').strip().rstrip('/')
    if env_url:
        return env_url
    port = os.environ.get('PORT', '9999')
    return f'http://127.0.0.1:{port}'


def build_password_reset_url(base_url: str, token: str, email: str) -> str:
    """Build a one-time reset URL; token is only used to open the form (change is POST)."""
    query = urlencode({'token': token, 'email': email})
    return f'{base_url.rstrip("/")}/reset-password?{query}'


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

        _carry_dark_mode_preference_into_session()
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

    def get_current_user_id(self) -> Optional[int]:
        """Get the current authenticated user id"""
        return self._storage_get('user_id')

    def get_current_email(self) -> Optional[str]:
        """Get the current authenticated user's email"""
        return self._storage_get('email')

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
        first_name: str = None,
        last_name: str = None,
    ) -> Tuple[bool, str]:
        """Create a new user account and associate with an organization."""
        if organization_id is None:
            return False, "Organization is required"

        org = self.db.getOrganizationById(organization_id)
        if not org:
            return False, "Invalid organization"

        first = (first_name or '').strip().lower()
        last = (last_name or '').strip().lower()
        if not first or not last:
            return False, "First name and last name are required"

        if self.db.userExists(username):
            return False, "Username already exists"

        if self.db.emailExists(email):
            return False, "Email already registered"

        password_hash, salt = self.hash_password(password)

        try:
            self.db.createUser(
                username,
                password_hash,
                salt,
                email,
                role,
                first_name=first,
                last_name=last,
            )
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

    def request_password_reset(self, email: str, base_url: Optional[str] = None) -> Tuple[bool, str]:
        """Request a password reset for the given email.

        Always returns a generic success message when the address is unknown so
        callers cannot probe which emails exist. When the user exists, emails a
        one-time reset link (plus the raw token as a fallback).
        """
        user = self.db.getUserByEmail(email)

        if not user:
            return True, RESET_REQUEST_SUCCESS_MESSAGE

        try:
            token = self.generate_reset_token()
            expires_at = datetime.now(timezone.utc) + PASSWORD_RESET_TOKEN_TTL

            self.db.createPasswordResetToken(user['id'], token, expires_at)

            origin = (base_url or resolve_app_base_url()).rstrip('/')
            reset_url = build_password_reset_url(origin, token, email)

            email_client = SendMailSimple()
            email_client.send(
                email,
                "Referee Mentor System Password Reset",
                f"""<h3>This is a message from the Referee Mentor Website.</h3>
                <table>
                    <tr><td>If you did not request a password reset, you can safely ignore this email.</td></tr>
                    <tr><td>This link expires in 15 minutes and can be used only once.</td></tr>
                    <tr><td style="padding-top: 12px;"><a href="{reset_url}">Reset your password</a></td></tr>
                    <tr><td style="padding-top: 12px;">If the button/link does not work, copy and paste this URL into your browser:</td></tr>
                    <tr><td style="word-break: break-all;">{reset_url}</td></tr>
                    <tr><td style="padding-top: 16px;">Or enter this token on the reset page:</td></tr>
                    <tr><td style="font-family: monospace; text-align: center;">{token}</td></tr>
                </table>
                """
            )

            return True, RESET_REQUEST_SUCCESS_MESSAGE
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


def require_admin(auth_manager: AuthManager) -> bool:
    """Require an authenticated admin; otherwise send them to login or the app."""
    if not auth_manager.is_authenticated():
        ui.navigate.to('/login')
        return False
    if not auth_manager.is_admin():
        ui.navigate.to(APP_HOME)
        return False
    return True


_AVATAR_COLORS = ('blue-6', 'indigo-6', 'purple-6', 'teal-6', 'orange-8', 'cyan-8', 'pink-6')


def _user_initials(username: Optional[str]) -> str:
    cleaned = (username or '?').replace('.', ' ').replace('_', ' ').replace('-', ' ').strip()
    parts = [part for part in cleaned.split() if part]
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    token = parts[0] if parts else '?'
    return token[:2].upper()


def _avatar_color(username: Optional[str]) -> str:
    name = username or 'user'
    return _AVATAR_COLORS[sum(ord(ch) for ch in name) % len(_AVATAR_COLORS)]


def _app_version() -> str:
    try:
        with open('VERSION', 'r', encoding='utf-8') as version_file:
            return version_file.read().strip()
    except OSError:
        return ''


def get_dark_mode_preference() -> bool:
    """Saved appearance: session first, then this browser, else dark."""
    try:
        if DARK_MODE_STORAGE_KEY in app.storage.user:
            return bool(app.storage.user[DARK_MODE_STORAGE_KEY])
    except RuntimeError:
        pass
    try:
        if DARK_MODE_STORAGE_KEY in app.storage.browser:
            return bool(app.storage.browser[DARK_MODE_STORAGE_KEY])
    except RuntimeError:
        pass
    return DEFAULT_DARK_MODE


def persist_dark_mode_preference(enabled: bool) -> None:
    enabled = bool(enabled)
    try:
        app.storage.user[DARK_MODE_STORAGE_KEY] = enabled
    except RuntimeError:
        logging.debug('Could not persist dark mode to user storage')
    try:
        app.storage.browser[DARK_MODE_STORAGE_KEY] = enabled
    except RuntimeError:
        logging.debug('Could not persist dark mode to browser storage')


def _carry_dark_mode_preference_into_session() -> None:
    """Keep the browser theme after login (user storage is empty on a new session)."""
    if DARK_MODE_STORAGE_KEY in app.storage.user:
        return
    try:
        if DARK_MODE_STORAGE_KEY in app.storage.browser:
            app.storage.user[DARK_MODE_STORAGE_KEY] = bool(
                app.storage.browser[DARK_MODE_STORAGE_KEY]
            )
    except RuntimeError:
        logging.debug('Could not read dark mode from browser storage at login')


def apply_app_dark_mode(*, authenticated: bool = True):
    """One DarkMode element per page. Authenticated pages follow the saved toggle."""
    if not authenticated:
        return ui.dark_mode(False)

    def _on_change(e) -> None:
        persist_dark_mode_preference(bool(e.value))

    return ui.dark_mode(get_dark_mode_preference(), on_change=_on_change)


def _load_help_markdown() -> str:
    try:
        with open(_USER_GUIDE_PATH, 'r', encoding='utf-8') as guide_file:
            content = guide_file.read()
    except OSError:
        return 'The user guide is not available in this deployment.'
    return content.replace(_USER_GUIDE_IMAGE_PREFIX, _USER_GUIDE_IMAGE_URL)


def _auth_screen_help_link() -> None:
    ui.link('Help', HELP_PATH).classes('w-full text-center text-gray-500 mt-4 no-underline')


def _organization_display(auth_manager: AuthManager) -> str:
    org_name = auth_manager.get_current_organization_name()
    if org_name:
        return org_name
    if auth_manager.get_current_organization_id() is not None:
        return '(unknown)'
    return 'not set'


def _account_menu_item(label: str, icon: str, on_click, *, color: Optional[str] = None) -> None:
    item = ui.menu_item(on_click=on_click)
    if color:
        item.props(f'text-color={color}')
    with item:
        with ui.row().classes('items-center gap-3 no-wrap w-full'):
            ui.icon(icon, size='xs').classes('opacity-80')
            ui.label(label)


def render_account_avatar(
    auth_manager: AuthManager,
    *,
    size: str = '40px',
    font_size: str = '15px',
) -> None:
    """Render the current user's photo, or initials if none is set."""
    username = auth_manager.get_current_user() or 'user'
    initials = _user_initials(username)
    color = _avatar_color(username)
    photo = avatar_data_url(auth_manager.get_current_user_id())
    with ui.avatar(color=color, text_color='white', size=size, font_size=font_size):
        if photo:
            ui.image(photo).classes('w-full h-full')
        else:
            ui.label(initials)


def render_help_menu() -> None:
    """Header help control. Ask-a-question can be added to this menu later."""
    with ui.button(color=None).props(
        'flat round dense unelevated aria-label="Help"'
    ).classes('app-help-btn shrink-0 text-white'):
        ui.icon('help_outline')
        with ui.menu().props('auto-close anchor="bottom right" self="top right"').classes('app-help-menu'):
            _account_menu_item(
                'View Documentation',
                'menu_book',
                lambda: ui.navigate.to(HELP_PATH),
            )


def render_user_menu(auth_manager: AuthManager) -> None:
    """Render a header avatar that opens account, settings, and admin actions."""
    username = auth_manager.get_current_user() or 'user'
    email = auth_manager.get_current_email()
    role = auth_manager.get_user_role()
    org = _organization_display(auth_manager)
    version = _app_version()

    with ui.button(color=None).props(
        'flat round dense unelevated aria-label="Account menu"'
    ).classes('app-account-btn shrink-0'):
        render_account_avatar(auth_manager, size='40px', font_size='15px')
        with ui.menu().props('auto-close anchor="bottom right" self="top right"').classes('app-account-menu'):
            with ui.item().props('dense'):
                with ui.row().classes('items-center gap-3 no-wrap py-1'):
                    render_account_avatar(auth_manager, size='36px', font_size='14px')
                    with ui.column().classes('gap-0 min-w-0'):
                        ui.label(username).classes('font-semibold leading-tight')
                        if email:
                            ui.label(email).classes('text-xs text-gray-400 leading-tight truncate max-w-[14rem]')
                        details = ' · '.join(part for part in (org, role) if part)
                        if details:
                            ui.label(details).classes('text-xs text-gray-400 leading-tight truncate max-w-[14rem]')
            ui.separator()
            _account_menu_item('Settings', 'settings', lambda: ui.navigate.to('/settings'))
            if auth_manager.is_admin():
                ui.separator()
                ui.label('Admin').classes('text-xs uppercase tracking-wide text-gray-400 px-4 pt-2 pb-1')
                _account_menu_item('User Management', 'group', lambda: ui.navigate.to('/admin/users'))
                _account_menu_item('User Activity', 'history', lambda: ui.navigate.to('/admin/user-activity'))
                _account_menu_item('Organizations', 'apartment', lambda: ui.navigate.to('/admin/organizations'))
            ui.separator()
            _account_menu_item('Log out', 'logout', auth_manager.logout, color='negative')
            if version:
                ui.label(f'Version {version}').classes(
                    'text-xs text-gray-500 px-4 py-2 text-right'
                )


def render_app_header(auth_manager: AuthManager, title: str = 'Referee Mentor System'):
    """Render the app header with a home link and account avatar menu."""
    dark = apply_app_dark_mode(authenticated=auth_manager.is_authenticated())
    ui.add_head_html('''
    <style>
        .app-account-btn {
            padding: 0 !important;
            min-width: 40px !important;
            min-height: 40px !important;
        }
        .app-account-btn .q-btn__content {
            padding: 0 !important;
        }
        .app-account-btn .q-avatar img,
        .app-account-menu .q-avatar img {
            object-fit: cover;
            width: 100%;
            height: 100%;
        }
        .app-account-menu {
            min-width: 16.5rem;
            max-width: min(20rem, calc(100vw - 16px));
        }
        .app-help-btn {
            color: #fff !important;
            min-width: 40px !important;
            min-height: 40px !important;
        }
        .app-help-btn:hover {
            background: rgba(255, 255, 255, 0.12) !important;
        }
        .app-help-menu {
            min-width: 13rem;
        }
        .app-header-divider {
            width: 1px;
            align-self: stretch;
            margin: 6px 2px;
            background: rgba(255, 255, 255, 0.25);
        }
        .app-header-brand,
        .app-header-brand:hover,
        .app-header-brand:visited {
            color: #fff !important;
            text-decoration: none !important;
        }
        .app-header-title-full { display: none; }
        .app-header-title-short { display: inline; }
        @media (min-width: 640px) {
            .app-header-title-full { display: inline; }
            .app-header-title-short { display: none; }
        }
    </style>
    ''')
    home_target = APP_HOME if auth_manager.is_authenticated() else '/'
    with ui.header().classes('bg-blue-900 text-white items-center px-3 gap-2 flex-nowrap'):
        with ui.link(target=home_target).classes('app-header-brand min-w-0'):
            with ui.row().classes('items-center gap-2 no-wrap'):
                ui.label('🏆').classes('text-xl')
                ui.label(title).classes('app-header-title-full text-xl font-bold truncate')
                short_title = 'RefMentor' if title == 'Referee Mentor System' else title
                ui.label(short_title).classes('app-header-title-short text-lg font-bold truncate')
        ui.space()
        render_help_menu()
        ui.element('div').classes('app-header-divider')
        if auth_manager.is_authenticated():
            render_user_menu(auth_manager)
        else:
            ui.link('Sign In', '/login').classes(
                'text-white font-semibold no-underline px-2 py-1 shrink-0'
            )
    return dark


@ui.page(HELP_PATH)
def help_page():
    """Public user guide."""
    auth_manager = AuthManager()
    ui.add_head_html('<link rel="manifest" href="/static/manifest.json">')
    ui.add_head_html('''
    <style>
        .help-doc {
            max-width: 52rem;
            margin: 0 auto;
            padding: 1.5rem 1rem 3.5rem;
            line-height: 1.6;
        }
        .help-doc img {
            max-width: 100%;
            height: auto;
            border-radius: 0.5rem;
            box-shadow: 0 8px 24px rgba(11, 31, 77, 0.16);
            margin: 0.75rem 0 1.25rem;
        }
        .help-doc table {
            width: 100%;
            border-collapse: collapse;
            margin: 1rem 0 1.5rem;
            font-size: 0.95rem;
        }
        .help-doc th,
        .help-doc td {
            border: 1px solid color-mix(in srgb, currentColor 18%, transparent);
            padding: 0.45rem 0.7rem;
            text-align: left;
            vertical-align: top;
        }
        .help-doc th {
            background: color-mix(in srgb, currentColor 8%, transparent);
        }
        .help-doc pre {
            overflow-x: auto;
        }
    </style>
    ''')
    render_app_header(auth_manager)
    with ui.element('div').classes('help-doc'):
        ui.markdown(_load_help_markdown())


@ui.page('/login')
def login_page():
    """Login page"""
    auth_manager = AuthManager()
    if auth_manager.is_authenticated():
        ui.navigate.to(APP_HOME)
        return


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
                logging.info(f"User {username_input.value} logged in from IP {ip_info}, navigating to {APP_HOME}")
                ui.navigate.to(APP_HOME)
            else:
                logging.error(f"User {username_input.value} failed to login using organization {org_id}")
                with message_area:
                    ui.label('Invalid username, password, or you do not have access to the selected organization.').classes('text-red-500')

        ui.button('Login', on_click=do_login).classes('w-full mt-4').props('color=primary')
        ui.button('Forgot Password?', on_click=lambda: ui.navigate.to('/forgot-password')).classes('w-full mt-2').props('flat')
        ui.button('Back to Home', on_click=lambda: ui.navigate.to('/')).classes('w-full mt-2').props('flat')
        _auth_screen_help_link()
        ui.label('Version: ' + open('VERSION', 'r').read().strip()).classes('text-gray-600 text-right w-full mb-6')


@ui.page('/forgot-password')
def forgot_password_page(request: Request):
    """Forgot password page — stay here after send; email link opens the reset form."""
    auth_manager = AuthManager()
    base_url = resolve_app_base_url(request)

    with ui.card().classes('login-container'):
        ui.label('🏆 Referee Mentor System').classes('text-2xl font-bold text-center w-full mb-2')
        ui.label('Reset Your Password').classes('text-gray-600 text-center w-full mb-6')

        form_area = ui.column().classes('w-full')
        with form_area:
            email_input = ui.input('Email Address', placeholder='Enter your email').classes('w-full')
            message_area = ui.column().classes('w-full')

            def do_reset():
                message_area.clear()
                if not email_input.value:
                    with message_area:
                        ui.label('Please enter your email address').classes('text-red-500')
                    return

                success, message = auth_manager.request_password_reset(
                    email_input.value.strip(),
                    base_url=base_url,
                )
                if success:
                    app.storage.user['reset_email'] = email_input.value.strip()
                    form_area.clear()
                    with form_area:
                        ui.label('Check your email').classes('text-xl font-semibold text-center w-full mb-2')
                        ui.label(message).classes('text-gray-600 text-center w-full mb-4')
                        ui.label(
                            'Open the reset link from that email to choose a new password. '
                            'You can close this tab.'
                        ).classes('text-gray-500 text-center w-full mb-6 text-sm')
                        with ui.row().classes('w-full gap-2 justify-center'):
                            ui.button('Back to Login', on_click=lambda: ui.navigate.to('/login')).props('color=primary')
                        ui.button(
                            'Enter token instead',
                            on_click=lambda: ui.navigate.to('/reset-password'),
                        ).classes('w-full mt-4').props('flat')
                else:
                    with message_area:
                        ui.label(message).classes('text-red-500')

            with ui.row().classes('w-full gap-2 mt-4'):
                ui.button('Send Reset Email', on_click=do_reset).props('color=primary')
                ui.button('Cancel', on_click=lambda: ui.navigate.to('/login')).props('color=grey')

            ui.button(
                'Already have a token?',
                on_click=lambda: ui.navigate.to('/reset-password'),
            ).classes('w-full mt-4').props('flat')
        _auth_screen_help_link()


@ui.page('/reset-password')
def reset_password_page(request: Request):
    """Reset password page — token/email may come from the email deep link."""
    auth_manager = AuthManager()

    query_token = (request.query_params.get('token') or '').strip()
    query_email = (request.query_params.get('email') or '').strip()
    stored_email = (app.storage.user.get('reset_email') or '').strip()
    initial_email = query_email or stored_email

    if query_token or query_email:
        # Keep token out of browser history / shareable address bar after load
        ui.run_javascript('history.replaceState(null, "", "/reset-password")')

    with ui.card().classes('login-container'):
        ui.label('🏆 Referee Mentor System').classes('text-2xl font-bold text-center w-full mb-2')
        ui.label('Enter New Password').classes('text-gray-600 text-center w-full mb-6')
        if query_token:
            ui.label('Token loaded from your email link. Choose a new password below.').classes(
                'text-gray-500 text-center w-full mb-4 text-sm'
            )
        else:
            ui.label('Paste the token from your email, then choose a new password.').classes(
                'text-gray-500 text-center w-full mb-4 text-sm'
            )

        email_input = ui.input('Email', value=initial_email).classes('w-full')
        # Hide the token when it came from the email link; still required for paste flow.
        token_input = None
        if not query_token:
            token_input = ui.input(
                'Reset Token',
                placeholder='Paste token from email if not using the link',
            ).classes('w-full').props('input-class=font-mono')
        password_input = ui.input('New Password', placeholder='Enter new password', password=True).classes('w-full')
        confirm_input = ui.input('Confirm Password', placeholder='Confirm new password', password=True).classes('w-full')

        message_area = ui.column().classes('w-full')

        def do_reset():
            message_area.clear()
            token = query_token if query_token else (token_input.value or '').strip()

            if not all([email_input.value, token, password_input.value, confirm_input.value]):
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
                token,
                password_input.value,
                email_input.value.strip(),
            )

            with message_area:
                if success:
                    ui.label(message).classes('text-green-500')
                    ui.label('You can now log in with your new password.').classes('text-gray-600')
                    if 'reset_email' in app.storage.user:
                        del app.storage.user['reset_email']
                    ui.timer(2.0, lambda: ui.navigate.to('/login'), once=True)
                else:
                    ui.label(message).classes('text-red-500')

        with ui.row().classes('w-full gap-2 mt-4'):
            ui.button('Reset Password', on_click=do_reset).props('color=primary')
            ui.button('Cancel', on_click=lambda: ui.navigate.to('/login')).props('color=grey')
        _auth_screen_help_link()


def _settings_detail_row(label: str, value: str) -> None:
    with ui.row().classes('w-full items-baseline justify-between gap-4 py-1'):
        ui.label(label).classes('text-sm text-gray-400')
        ui.label(value).classes('text-sm font-medium text-right')


def _render_change_password_form(auth_manager: AuthManager) -> None:
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
                ui.notify(message + ' Please log in again with your new password.')
                ui.timer(2.0, lambda: auth_manager.logout(), once=True)
            else:
                ui.label(message).classes('text-red-500')

    with ui.row().classes('w-full gap-2 mt-4 flex-wrap'):
        ui.button('Change Password', on_click=do_change).props('color=primary')
        ui.button('Cancel', on_click=lambda: ui.navigate.to(APP_HOME)).props('color=grey')


@ui.page('/settings')
def settings_page():
    """Account settings for authenticated users."""
    auth_manager = AuthManager()

    if not auth_manager.is_authenticated():
        ui.navigate.to('/login')
        return

    dark = render_app_header(auth_manager)

    username = auth_manager.get_current_user() or ''
    email = auth_manager.get_current_email() or '—'
    role = auth_manager.get_user_role() or '—'
    org = _organization_display(auth_manager)
    user_id = auth_manager.get_current_user_id()

    with ui.column().classes('w-full max-w-lg mx-auto p-4 gap-4'):
        ui.label('Settings').classes('text-2xl font-bold')

        with ui.card().classes('w-full p-4'):
            ui.label('Profile photo').classes('text-lg font-semibold mb-2')
            with ui.row().classes('items-center gap-4 mb-3'):
                render_account_avatar(auth_manager, size='72px', font_size='24px')
                with ui.column().classes('gap-1'):
                    ui.label('This appears in the header on every page.').classes('text-sm text-gray-400')
                    ui.label("JPEG, PNG, or WebP. We'll crop it to a square.").classes('text-sm text-gray-400')

            async def handle_photo_upload(event):
                if user_id is None:
                    ui.notify('Could not update photo for this account.', type='negative')
                    return
                try:
                    data = await event.file.read()
                    save_avatar(user_id, data)
                except ValueError as exc:
                    ui.notify(str(exc), type='negative')
                    return
                except OSError:
                    ui.notify('Could not save that photo. Please try again.', type='negative')
                    return
                ui.notify('Profile photo updated.')
                ui.navigate.reload()

            ui.upload(
                label='Upload photo',
                auto_upload=True,
                max_file_size=MAX_UPLOAD_BYTES,
                on_upload=handle_photo_upload,
                on_rejected=lambda: ui.notify(
                    "That file is too large or isn't a supported image.",
                    type='negative',
                ),
            ).props(
                'accept=".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp"'
            ).classes('w-full avatar-upload')

            if has_avatar(user_id) and user_id is not None:
                def remove_photo():
                    delete_avatar(user_id)
                    ui.notify('Profile photo removed.')
                    ui.navigate.reload()

                ui.button('Remove photo', on_click=remove_photo).props('flat color=negative')

        with ui.card().classes('w-full p-4'):
            ui.label('Profile').classes('text-lg font-semibold mb-2')
            _settings_detail_row('Username', username)
            _settings_detail_row('Email', email)
            _settings_detail_row('Role', role)
            _settings_detail_row('Organization', org)

        with ui.card().classes('w-full p-4'):
            ui.label('Appearance').classes('text-lg font-semibold mb-2')
            ui.switch('Dark mode', value=bool(dark.value)).bind_value(dark)
            ui.label('Applies to the app, Settings, Help, and admin pages on this device.').classes(
                'text-sm text-gray-400 mt-1'
            )

        with ui.card().classes('w-full p-4'):
            ui.label('Password').classes('text-lg font-semibold mb-1')
            ui.label(PASSWORD_REQUIREMENTS).classes('text-sm text-gray-400 mb-4')
            _render_change_password_form(auth_manager)


@ui.page('/change-password')
def change_password_page():
    """Keep old bookmarks working; password changes live in Settings."""
    ui.navigate.to('/settings')


@ui.page('/admin/organizations')
def organizations_page():
    """Organization management (admin only)."""
    auth_manager = AuthManager()

    if not require_admin(auth_manager):
        return

    render_app_header(auth_manager)

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

    if not require_admin(auth_manager):
        return

    render_app_header(auth_manager)

    ui.label('User Management').classes('text-xl font-bold px-4 pt-4')

    with ui.tabs() as tabs:
        create_tab = ui.tab('Create User')
        manage_tab = ui.tab('Manage Users')

    with ui.tab_panels(tabs, value=create_tab).classes('w-full'):
        with ui.tab_panel(create_tab):
            with ui.card().classes('max-w-md mx-auto p-6'):
                ui.label('Create New User').classes('text-xl font-bold mb-4')

                new_username = ui.input('Username').classes('w-full')
                new_first_name = ui.input('First Name').classes('w-full')
                new_last_name = ui.input('Last Name').classes('w-full')
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

                    if not all([
                        new_username.value,
                        new_first_name.value,
                        new_last_name.value,
                        new_email.value,
                        new_password.value,
                        confirm_password.value,
                    ]):
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
                        first_name=new_first_name.value,
                        last_name=new_last_name.value,
                    )

                    with message_area:
                        if success:
                            ui.label(message).classes('text-green-500')
                            new_username.value = ''
                            new_first_name.value = ''
                            new_last_name.value = ''
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

    if not require_admin(auth_manager):
        return

    render_app_header(auth_manager)

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

