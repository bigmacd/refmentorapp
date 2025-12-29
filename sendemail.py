import base64
import os
import pickle
import smtplib

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


class SendMailSimple():

    def __init__(self):
        self.mailserver = 'smtp.protonmail.ch'
        self.serverPort = 587

        self.user = os.environ.get('EMAIL_USER')
        self.token = os.environ.get('EMAIL_TOKEN')


    def message(self, recipient, subject, message):
        self.message = MIMEMultipart()
        self.message['From'] = self.user
        self.message['To'] = recipient
        self.message['Subject'] = subject
        #self.message.attach(MIMEText(message, 'plain'))
        self.message.attach(MIMEText(message, 'html'))


    def send(self, recipient: str, subject: str, message: str) -> None:
        self.message(recipient, subject, message)
        with smtplib.SMTP(self.mailserver, self.serverPort) as server:
            server.starttls()
            server.login(self.user, self.token)
            server.send_message(self.message)



class GmailAPIEmail():

    def __init__(self):

        # Define Gmail API scope for sending email
        self.SCOPES = ['https://www.googleapis.com/auth/gmail.send']
        self.creds = None
        self.tokenfile = 'token.pickle'
        self.service = self.Authenticate()

    def Authenticate(self):

        # Run OAuth 2.0 flow to get credentials
        if os.path.exists(self.tokenfile):
            with open(self.tokenfile, 'rb') as token:
                creds = pickle.load(token)
        else:
            print("No token file found")
            return None
        # If no valid credentials, authenticate and save the token
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())  # Refresh access token automatically using the refresh token
            else:
                flow = InstalledAppFlow.from_client_secrets_file('gmailcreds.json', self.SCOPES)
                creds = flow.run_local_server(port=0)
            with open(self.tokenfile, 'wb') as token:
                pickle.dump(creds, token)
        # Build the Gmail API service
        return build('gmail', 'v1', credentials=creds)


    def send(self, _to: str, subject: str, message: str) -> None:

        if self.service is None:
            print("No Gmail service available, cannot send email")
        else:
            try:
                # Create email message
                msg = MIMEText(message)
                msg['to'] = _to
                msg['subject'] = subject

                # Encode the message in base64 format
                create_message = {'raw': base64.urlsafe_b64encode(msg.as_bytes()).decode()}

                # Send the email
                self.service.users().messages().send(userId='me', body=create_message).execute()

            except HttpError as error:
                print(f'An error occurred: {error}')


if __name__ == '__main__':

    g = SendMailSimple()
    g.send("martin.cooley@gmail.com",
           "Referee Mentor System Password Reset",
           """<h3>This is a message from the Referee Mentor Website.</h3>
                 <table>
                    <tr>
                    <td>If you did not request a password reset, you can safely ignore this email.</td>
                    <tr>
                    <td><b>Use the following token to reset your password:</b></td>
                    </tr>
                    <tr>
                    <td style="text-align: center; vertical-align: middle;">This is a test message</td>
                    </tr>
                 </table></p>
           """)

    # g = GmailAPIEmail()
    # g.send('someuser@some.org', 'test subject', 'test message')

