#!/usr/bin/env python
"""
ZoomWebSocket - A python class to interact with ZoomWebSockets.
Written by James Ferris
Feel free to use as needed.
Zoom API Reference: https://developers.zoom.us/docs/api/rest/reference/zoom-api/methods/#tag/Meetings
"""

import os
import sys
import json
import datetime
import signal
import logging
from logging.handlers import RotatingFileHandler
import smtplib
from email.message import EmailMessage
import requests
from requests.auth import HTTPBasicAuth
import websocket
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

load_dotenv()


class ZoomWebSocket:
    ACCOUNT_ID: str = os.getenv("ACCOUNT_ID")
    CLIENT_ID: str = os.getenv("CLIENT_ID")
    CLIENT_SECRET: str = os.getenv("CLIENT_SECRET")
    meeting_id: str = "83148128109"

    # Define a list of (user, phone_number) tuples, IE numbers we want to call when the meeting starts
    participants = [
        ("IT Help Desk", "15554560001")
        # ("Network Oncall Engineer", "15554561000"),
        # ("Server Oncall Enginner", "15554562000")
    ]

    def __init__(self) -> None:
        """Initialize the ZoomWebSocket instance, set up logging, session, and scheduler."""
        self.start_time: datetime.datetime = datetime.datetime.now()

        # Set up rotating log handler
        log_file = "ZoomWebSocketLog.txt"
        log_handler = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=3)
        log_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        self.logger = logging.getLogger("ZoomWebSocket")
        self.logger.setLevel(logging.INFO)
        self.logger.addHandler(log_handler)
        self.logger.info(f"ZoomWebSocket started at {self.start_time}")

        # Create a persistent requests session
        self.session = requests.Session()

        # Get the access token
        self.ACCESS_TOKEN = self.get_access_token()
        self.logger.info("Access token retrieved.")

        # Set up the scheduler for heartbeat and token refresh
        self.scheduler = BackgroundScheduler()
        self.scheduler.add_job(self.send_heartbeat, 'interval', seconds=20)
        self.scheduler.add_job(self.refresh_token, 'interval', minutes=55)
        self.scheduler.start()

    def get_access_token(self) -> str:
        """
        Retrieve the access token from Zoom.
        
        Returns:
            str: The access token if successful, otherwise an empty string.
        """
        url = "https://zoom.us/oauth/token"
        data = {
            'grant_type': 'account_credentials',
            'account_id': self.ACCOUNT_ID
        }
        try:
            response = self.session.post(
                url,
                auth=HTTPBasicAuth(self.CLIENT_ID, self.CLIENT_SECRET),
                data=data,
                timeout=10
            )
            response.raise_for_status()
            json_response = response.json()
            self.access_token_expires = datetime.datetime.now() + datetime.timedelta(hours=1)
            self.logger.info(f"Access Token Expires {self.access_token_expires}")
            return json_response.get("access_token", "")
        except requests.exceptions.RequestException as e:
            error_msg = f"Error fetching Access Token: {str(e)}"
            print(error_msg)
            self.logger.error(error_msg)
            return ""

    def refresh_token(self) -> None:
        """Refresh the access token using the get_access_token method."""
        self.logger.info("Refreshing access token...")
        new_token = self.get_access_token()
        if new_token:
            self.ACCESS_TOKEN = new_token
            self.logger.info("New access token acquired.")
        else:
            self.logger.error("Failed to refresh access token.")

    def send_heartbeat(self) -> None:
        """Send a heartbeat message through the WebSocket to Zoom."""
        try:
            if hasattr(self, 'ws'):
                self.ws.send('{ "module": "heartbeat" }')
                self.logger.info("Heartbeat sent to Zoom")
            else:
                self.logger.warning("WebSocket not connected; heartbeat not sent.")
        except Exception as e:
            self.logger.error("Error sending heartbeat: " + str(e))

    def process_message(self, message: str) -> None:
        """
        Process a message received via WebSocket.

        Args:
            message (str): The raw JSON string received.
        """
        try:
            j = json.loads(message)
            self.logger.info(f"{j.get('module')} message received")
            print(json.dumps(j, indent=4))
            self.logger.info(json.dumps(j, indent=4))
        except Exception as e:
            self.logger.error("Error processing message JSON: " + str(e))
            return

        if j.get('module') == 'message':
            try:
                content_string = j['content']
                content = json.loads(content_string)
            except Exception as e:
                self.logger.error("Error processing content JSON: " + str(e))
                return

            try:
                event = content.get('event')
                if event == "meeting.participant_left":
                    self.process_leave_event(content)
                elif event == "meeting.ended":
                    self.process_meeting_end_event(content)
                elif event == "meeting.participant_joined":
                    self.process_participant_joined_event(content)
                elif event == "meeting.started":
                    self.process_meeting_started_event(content)
            except Exception as e:
                self.logger.error("Error processing event: " + str(e))
        elif j.get('module') == 'heartbeat':
            self.logger.info(f"Received heartbeat response. Success = {str(j.get('success'))}")
            print(f"{datetime.datetime.now()} - Received heartbeat response. Success = {str(j.get('success'))}")

    def process_leave_event(self, content: dict) -> None:
        """
        Process an event when a participant leaves a meeting.

        Args:
            content (dict): The event content dictionary.
        """
        try:
            meeting = content['payload']['object']['id']
            user = content['payload']['object']['participant']['user_name']
            topic = content['payload']['object']['topic']
            if meeting == self.meeting_id:
                print(f"{user} has left the meeting {topic}!")
                self.logger.info(f"{user} has left the meeting {topic}!")
                details = self.get_meeting_details(self.meeting_id)
                participant_count = details.get("participants", 0)
                if participant_count == 0:
                    self.logger.info("There are zero participants in the meeting. Ending call.")
                    self.end_meeting(self.meeting_id)
        except Exception as e:
            self.logger.error("Error in process_leave_event: " + str(e))

    def process_meeting_end_event(self, content: dict) -> None:
        """
        Process an event when a meeting ends.

        Args:
            content (dict): The event content dictionary.
        """
        try:
            meeting = content['payload']['object']['id']
            print(f"{meeting} has ended!")
            self.logger.info(f"{meeting} has ended!")
        except Exception as e:
            self.logger.error("Error in process_meeting_end_event: " + str(e))

    def process_participant_joined_event(self, content: dict) -> None:
        """
        Process an event when a participant joins a meeting.

        Args:
            content (dict): The event content dictionary.
        """
        try:
            user = content['payload']['object']['participant']['user_name']
            topic = content['payload']['object']['topic']
            print(f"{user} has joined the meeting {topic}!")
            self.logger.info(f"{user} has joined the meeting {topic}!")
        except Exception as e:
            self.logger.error("Error in process_participant_joined_event: " + str(e))

    def process_meeting_started_event(self, content: dict) -> None:
        """
        Process an event when a meeting starts.

        Args:
            content (dict): The event content dictionary.
        """
        try:
            meeting = content['payload']['object']['id']
            print(f"Meeting ID: {meeting} has started!")
            self.logger.info(f"Meeting ID: {meeting} has started!")
            if meeting == self.meeting_id:
                print("Meeting has started. Placing calls to participants!")
                self.logger.info("Meeting has started. Placing calls to participants!")
                for user, phone in self.participants:
                    self.place_call(meeting, user, phone)
        except Exception as e:
            self.logger.error("Error in process_meeting_started_event: " + str(e))

    def on_message(self, ws: websocket.WebSocketApp, message: str) -> None:
        """WebSocket on_message handler."""
        self.process_message(message)

    def on_error(self, ws: websocket.WebSocketApp, error: Exception) -> None:
        """WebSocket on_error handler."""
        error_msg = f"Encountered error: {str(error)}"
        print(error_msg)
        self.logger.error(error_msg)

    def on_close(self, ws: websocket.WebSocketApp, close_status_code: int, close_msg: str) -> None:
        """WebSocket on_close handler."""
        print("Connection closed")
        self.logger.info("Connection closed")

    def on_open(self, ws: websocket.WebSocketApp) -> None:
        """WebSocket on_open handler."""
        print("Connection opened")
        # Save the WebSocket reference for heartbeat
        self.ws = ws

    def place_call(self, meeting_ID: str, name: str, phone_number: str) -> None:
        """
        Place a call to a participant to join the meeting.

        Args:
            meeting_ID (str): The meeting ID.
            name (str): The invitee's name.
            phone_number (str): The invitee's phone number.
        """
        meeting_options = {
            "method": "participant.invite.callout",
            "params": {
                "invitee_name": str(name),
                "phone_number": str(phone_number),
                "invite_options": {
                    "require_greeting": False,
                    "require_pressing_one": False
                },
            }
        }
        headers = {
            'authorization': 'Bearer ' + self.ACCESS_TOKEN,
            'content-type': 'application/json'
        }
        url = f'https://api.zoom.us/v2/live_meetings/{meeting_ID}/events'
        try:
            self.logger.info(f"Placing call to {phone_number} to join {name} for meeting {meeting_ID}")
            response = self.session.patch(url, headers=headers, data=json.dumps(meeting_options))
            print(response.text)
            self.logger.info(f"Place call request returned {str(response)}")
        except Exception as e:
            self.logger.error("Error placing call: " + str(e))

    def get_meeting_details(self, meeting_id: str) -> dict:
        """
        Retrieve meeting details.

        Args:
            meeting_id (str): The meeting ID.
            
        Returns:
            dict: The meeting details or an empty dictionary if an error occurs.
        """
        headers = {
            'authorization': 'Bearer ' + self.ACCESS_TOKEN,
            'content-type': 'application/json'
        }
        try:
            response = self.session.get(f'https://api.zoom.us/v2/metrics/meetings/{meeting_id}', headers=headers)
            if response.status_code == 200:
                self.logger.info(f"Successfully retrieved meeting details for meeting {meeting_id}")
            else:
                self.logger.error("Error retrieving meeting details: " + response.text)
            return response.json()
        except Exception as e:
            self.logger.error("Error in get_meeting_details: " + str(e))
            return {}

    def end_meeting(self, meeting_id: str) -> int:
        """
        End a meeting.

        Args:
            meeting_id (str): The meeting ID.
            
        Returns:
            int: The HTTP status code from the request.
        """
        action = {"action": "end"}
        headers = {
            'authorization': 'Bearer ' + self.ACCESS_TOKEN,
            'content-type': 'application/json'
        }
        try:
            response = self.session.put(f'https://api.zoom.us/v2/meetings/{meeting_id}/status',
                                        headers=headers, data=json.dumps(action))
            if response.status_code == 204:
                self.logger.info(f"Successfully ended meeting {meeting_id}")
            else:
                self.logger.error("Error ending meeting: " + response.text)
            return response.status_code
        except Exception as e:
            self.logger.error("Exception in end_meeting: " + str(e))
            return -1

	# Update the IP of your SMTP server if you want to use this function to send an email
    def send_mail(self, to_email: list[str], subject: str, message: str,
                  server: str = '1.2.3.4', from_email: str = 'critical.incident@example.com') -> None:
        """
        Send an email.

        Args:
            to_email (list[str]): List of recipient email addresses.
            subject (str): Subject of the email.
            message (str): Body of the email.
            server (str, optional): SMTP server address.
            from_email (str, optional): Sender email address.
        """
        try:
            msg = EmailMessage()
            msg['Subject'] = subject
            msg['From'] = from_email
            msg['To'] = ', '.join(to_email)
            msg.set_content(message)
            self.logger.info("Sending email.")
            with smtplib.SMTP(server) as smtp_server:
                smtp_server.set_debuglevel(1)
                smtp_server.send_message(msg)
            print('Successfully sent the mail.')
        except Exception as e:
            self.logger.error("Error sending email: " + str(e))

    def shutdown(self) -> None:
        """Gracefully shutdown the scheduler and close the WebSocket connection."""
        self.logger.info("Initiating graceful shutdown...")
        if self.scheduler:
            self.scheduler.shutdown(wait=False)
            self.logger.info("Scheduler shut down.")
        if hasattr(self, 'ws'):
            self.logger.info("Closing WebSocket connection...")
            try:
                self.ws.close()
            except Exception as e:
                self.logger.error("Error closing WebSocket: " + str(e))
        self.logger.info("Shutdown complete.")

    def run(self) -> None:
        """Establish and maintain the WebSocket connection."""
        websocket.enableTrace(False)
		# Copy your wss endpoint url from your Zoom application settings.  
		# Be sure to include &access_token= at the end of your url
        ws = websocket.WebSocketApp(
            "wss://ws.zoom.us/ws?subscriptionId=blahblahblah&access_token=" + str(self.ACCESS_TOKEN),
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close
        )
        try:
            ws.run_forever(reconnect=5)
        except Exception as e:
            self.logger.error("Error in WebSocket run_forever: " + str(e))


if __name__ == "__main__":
    zws = ZoomWebSocket()

    def graceful_shutdown(signum, frame) -> None:
        """Handle shutdown signals for graceful termination."""
        zws.logger.info("Shutdown signal received.")
        print("Shutdown signal received.")
        zws.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, graceful_shutdown)
    signal.signal(signal.SIGTERM, graceful_shutdown)

    zws.run()
