# Referee Mentoring App

This is the code for the website that allows USSF Soccer Mentors to view the current workload for the upcoming weekend, select games they wish to mentor, and then enter a mentor report once the mentoring session has been completed.

## Operation

## Auth Flow

Use the create_admin.py script to create an admin user.  Use that user to login and from there you can create additional users.

The Auth Manager is instantiated in the main ui code.  Then the requireAuth function is called indicating we need to authenticate the current user.

Since the user is not authenticated, the showLoginForm function is called so that the user can enter their credentials.
On that form, there are two paths:  Login or "Forgot Password".

### Login

The login path requires the user to enter their username and password.  Upon entering the data and pressing "Login", we call authenticateUser.  This looks the user up in the database and verifies the password by calling verifyPassword.

Of course we have to hash the password that was entered since that is how it is stored in the database.  Data referring to the authentication state of the user is stored during the session.  Then since the user is now authenticated, the user is shown a panel for logging out or chaning their password, as well as the main UI which opens on the "Enter a Report" tab.  From there, if the user presses the logout button, session state is cleared and we start all over again.

However, if the user misenters the username of password (or both), a toast like message is displayed indication they fat-fingered something.  This is in showLoginForm, and we clear the input before allowing the user to try again.

### Forgot Password

If the user is exasperated, they can click on the "Forgot Password" button.  This is the second path.
This goes through the same mascinations, but ends up at showForgotPasswordForm.  From there we have two paths depending on the email address entered.  In either case, for security reasons, we show a toast like message that says: "If the email exists in our system, a password reset link will be sent.

If the email address is not in our system, nothing happens.

If the email address is in our system, the showForgotPasswordForm calls requestPasswordReset in the auth manager.  This looks the user up via the supplied email address, and if not found provides a generic message "if your email address is in our system we just sent you an email" for example.  If the user was found, a reset token is generated and stored in the database with a timestamp so the token can be expired.  This reset token is sent to the user's email address.  We also display a form for the user to enter 1) the reset token, 2) the new password, and 3) confirm the password.

## We're In.  Not what?

There are 5 main areas for the mentor to use and they will be described in the follow sections.

### Enter a Mentor Report

When a mentor works with a referee or crew, their observations are entered on this form.

For regular users, the Select Mentor is defaulted to their name.  For admin users, this is a dropdown of all mentors.  This allows admins to enter reports on behalf of other mentors who, for whatever reason, cannot enter it themselves.

Mentoring is done on the weekends (this may change in the future), so there is a dropdown to select the day, typically one or more of Friday, Saturday, and/or Sunday.  When this drop changes, it drives changes to the following dropdown as well.

Next is the Select Venue dropdown.  This shows the athletic fields that are to be used on the date selected.  When this dropdown changes, it drives changes to the following dropdown as well.

Next is the Select Game dropdown.  This will be populated with time slots that are assigned games for that venue on that date.

Following the dropdowns, that is a series of checkboxes which represent the referee(s) that are assigned for that timeslot at that athletic field on that date.  Some soccer games have one referee, some have three.

Next is a comments field.  Here is where the mentor enters their observations about the referee or crew.  It is freeform text, but mentors will use a fairly consistent language as per their training from US Soccer.

Finally, there is another series of checkboxes, one for each referee that is assigned.  These checkboxes ask "Should any referee be revisited".  If the mentor thinks the referee needs additional guidance/support, they will check the box for that referee.

### Generate Reports

### See Current Workload

### Select Games to Mentor

### Calendar

Currently the calendar is not being used
