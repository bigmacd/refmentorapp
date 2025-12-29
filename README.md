# RefMentorAssignments

Code to generate workload for mentors for the upcoming weekend

## Operation

## Auth Flow

Use the create_admin.py script to create an admin user.  Use that user to login and from there you can create additional users.

The Auth Manager is instantiated in the main ui code.  Then the requireAuth function is called indicating we need to authenticate the current user.

Since the user is not authenticated, the showLoginForm function is called so that the user can enter their credentials.
On that form, there are two paths:  Login or "Forgot Password".

### Login

The login path requires the user to enter their username and password.  Upon entering the data and pressing Login, the way streamlit works is
that the page reloads so we start over, that is, we instantiate the Auth Manager.  Again, we requireAuth, and call showLoginForm again, but this time
we have a username and password, so we call authenticateUser.  This looks the user up in the database and verifies the password by calling verifyPassword.
Of course we have to hash the password that was entered since that is how it is stored in the database.  Data referring to the authentication state of the
user is stored in streamlit session state store.  Then since the user is now authenticated, the user is shown a panel for logging out as well as the main
streamlit UI.  From there, if the user presses the logout button, session state is cleared and we start all over again.

However, if the user misenters the username of password (or both), a toast like message is displayed indication they fucked up.  This is in showLoginForm, and we
should clear the input before allowing the user to try again.  (TODO)

### Forgot Password

If the user is exasperated, they can click on the "Forgot Password" button.  This is the second path.
This goes through the same mascinations, but ends up at showForgotPasswordForm.  From there we have two paths depending on the email address entered.
In either case, for security reasons, we show a toast like message that says: "If the email exists in our system, a password reset link will be sent.

If the email address is not in our system, nothing happens.

If the email address is in our system, the showForgotPasswordForm calls requestPasswordReset in the auth manager.  This looks the user up via the supplied email address, and if not found provides a generic message "if your email address is in our system we just sent you an email" for example.  If the user was found, a reset token is generated and stored in the database with a timestamp so the token can be expired.
