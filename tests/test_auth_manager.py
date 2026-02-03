"""
Unit tests for AuthManager password reset functionality
"""

import sys
import os
from pathlib import Path

# Add parent directory to path to import modules
sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta, timezone
from auth_nicegui import AuthManager


class TestAuthManagerPasswordReset(unittest.TestCase):
    """Test cases for password reset token functionality in AuthManager"""

    @patch('auth_nicegui.RefereeDbCockroach')
    def setUp(self, mock_db_class):
        """Set up test fixtures"""
        # Mock the database class to avoid actual DB connection
        mock_db_instance = Mock()
        mock_db_class.return_value = mock_db_instance
        
        self.auth_manager = AuthManager()
        # The database is already mocked via the patch
        self.auth_manager.db = mock_db_instance

    def tearDown(self):
        """Clean up after tests"""
        self.auth_manager = None

    @patch('auth_nicegui.SendMailSimple')
    @patch('auth_nicegui.datetime')
    def test_password_reset_token_expiry_is_4_hours_from_utc_now(self, mock_datetime, mock_email):
        """
        Test that password reset token expiry is set to exactly 4 hours
        from the current UTC time when request_password_reset is called.
        """
        # Arrange
        test_email = 'test@example.com'
        test_user = {
            'id': 123,
            'username': 'testuser',
            'email': test_email,
            'role': 'user'
        }
        
        # Set up a fixed UTC time for testing
        fixed_utc_time = datetime(2026, 1, 17, 19, 44, 29, tzinfo=timezone.utc)
        expected_expiry_time = fixed_utc_time + timedelta(hours=4)
        
        # Mock datetime.now to return our fixed time
        mock_datetime.now.return_value = fixed_utc_time
        
        # Mock the database methods
        self.auth_manager.db.getUserByEmail.return_value = test_user
        self.auth_manager.db.createPasswordResetToken = Mock()
        
        # Mock the email client
        mock_email_instance = Mock()
        mock_email.return_value = mock_email_instance
        
        # Act
        success, message = self.auth_manager.request_password_reset(test_email)
        
        # Assert
        self.assertTrue(success)
        self.auth_manager.db.getUserByEmail.assert_called_once_with(test_email)
        
        # Verify that createPasswordResetToken was called
        self.auth_manager.db.createPasswordResetToken.assert_called_once()
        
        # Extract the actual call arguments
        call_args = self.auth_manager.db.createPasswordResetToken.call_args[0]
        actual_user_id = call_args[0]
        actual_token = call_args[1]
        actual_expiry = call_args[2]
        
        # Verify the arguments
        self.assertEqual(actual_user_id, test_user['id'])
        self.assertIsInstance(actual_token, str)
        self.assertGreater(len(actual_token), 0)
        
        # Verify the expiry time is exactly 4 hours from now
        self.assertEqual(actual_expiry, expected_expiry_time)
        
        # Verify it's a timezone-aware datetime in UTC
        self.assertIsNotNone(actual_expiry.tzinfo)
        self.assertEqual(actual_expiry.tzinfo, timezone.utc)
        
        # Verify the difference is exactly 4 hours
        time_difference = actual_expiry - fixed_utc_time
        self.assertEqual(time_difference, timedelta(hours=4))

    @patch('auth_nicegui.SendMailSimple')
    def test_password_reset_token_expiry_uses_utc_timezone(self, mock_email):
        """
        Test that the password reset token expiry uses UTC timezone.
        """
        # Arrange
        test_email = 'test@example.com'
        test_user = {
            'id': 456,
            'username': 'anotheruser',
            'email': test_email,
            'role': 'user'
        }
        
        # Mock the database methods
        self.auth_manager.db.getUserByEmail.return_value = test_user
        self.auth_manager.db.createPasswordResetToken = Mock()
        
        # Mock the email client
        mock_email_instance = Mock()
        mock_email.return_value = mock_email_instance
        
        # Act
        success, message = self.auth_manager.request_password_reset(test_email)
        
        # Assert
        self.assertTrue(success)
        
        # Extract the expiry time from the call
        call_args = self.auth_manager.db.createPasswordResetToken.call_args[0]
        actual_expiry = call_args[2]
        
        # Verify it uses UTC timezone
        self.assertIsNotNone(actual_expiry.tzinfo)
        self.assertEqual(actual_expiry.tzinfo, timezone.utc)

    @patch('auth_nicegui.SendMailSimple')
    def test_password_reset_token_expiry_is_in_future(self, mock_email):
        """
        Test that the password reset token expiry is always in the future.
        """
        # Arrange
        test_email = 'future@example.com'
        test_user = {
            'id': 789,
            'username': 'futureuser',
            'email': test_email,
            'role': 'user'
        }
        
        # Mock the database methods
        self.auth_manager.db.getUserByEmail.return_value = test_user
        self.auth_manager.db.createPasswordResetToken = Mock()
        
        # Mock the email client
        mock_email_instance = Mock()
        mock_email.return_value = mock_email_instance
        
        # Capture the current time before the call
        time_before_call = datetime.now(timezone.utc)
        
        # Act
        success, message = self.auth_manager.request_password_reset(test_email)
        
        # Capture the current time after the call
        time_after_call = datetime.now(timezone.utc)
        
        # Assert
        self.assertTrue(success)
        
        # Extract the expiry time from the call
        call_args = self.auth_manager.db.createPasswordResetToken.call_args[0]
        actual_expiry = call_args[2]
        
        # Verify the expiry is in the future (at least 3 hours 59 minutes from now)
        # We use a slightly smaller threshold to account for test execution time
        min_expected_expiry = time_before_call + timedelta(hours=3, minutes=59)
        max_expected_expiry = time_after_call + timedelta(hours=4, minutes=1)
        
        self.assertGreater(actual_expiry, time_before_call)
        self.assertGreater(actual_expiry, min_expected_expiry)
        self.assertLess(actual_expiry, max_expected_expiry)


if __name__ == '__main__':
    unittest.main()
