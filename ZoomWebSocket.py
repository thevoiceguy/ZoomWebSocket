#!/usr/bin/env python
'''
	ZoomWebSocket - A python class to interact with ZoomWebSockets
	Written by James Ferris
	Feel free to use as needed.  Maybe it will help sombody out!
    Zoom API Reference:  https://developers.zoom.us/docs/api/rest/reference/zoom-api/methods/#tag/Meetings   
'''
import requests
import requests.auth
from requests.auth import HTTPBasicAuth
import json
import sys
import os
import datetime
import smtplib
from email.message import EmailMessage
import logging
import traceback
import websocket
import time
import rel
import io

try:
    import thread
except ImportError:
    import _thread as thread

class ZoomWebSocket:
    ACCOUNT_ID = "ENTER_ACCOUNT_ID" # Fill this in with your Zoom Account ID
    CLIENT_ID = "ENTER CLIENT_ID" # Fill this in with your Zoom Client ID
    CLIENT_SECRET = "Enter CLIENT_SECRET" # Fill this in with your Zoom Client Secret
    ACCESS_TOKEN = ""
    access_token_expires = ''
    start_time = ''
 
    # initalize
    def __init__(self):
        start_time = datetime.datetime.now()
        self.ACCESS_TOKEN = self.get_access_token()
        try:
            os.remove("ZoomWebSocketLog.txt")  # delete log file everytime script runs
        except OSError:
            pass
        
        logging.basicConfig(filename='ZoomWebSocketLog.txt', filemode='a', format='%(asctime)s - %(levelname)s - %(message)s')
        self.logger = logging.getLogger()
        self.logger.setLevel(logging.INFO)  # can be set to DEBUG for more info
        self.logger.info("ZoomWebSocket started at " + str(self.start_time))
        
    '''
        get_access_token()  Reaches out to Zoom to fetch the oauth access token needed to make API calls
    
        :param:   None
        :return:  Returns the access_token
    '''

    def get_access_token(self):
        url = "https://zoom.us/oauth/token"

        data = {
        'grant_type': 'account_credentials',
        'account_id': self.ACCOUNT_ID
        }

        r = requests.post(url, auth=HTTPBasicAuth(self.CLIENT_ID, self.CLIENT_SECRET), data=data)
        if (r.status_code == 200):
            jsonResponse = r.json()
            self.access_token_expires = datetime.datetime.now() + datetime.timedelta(hours=1)
            print("Access Token Expires " + str(self.access_token_expires))
            return jsonResponse["access_token"]
        else:
            print("Error fetching Access Token!" + str(r))
            return -1
        

    ''' 
        process_message(self, message)
        Function to process the messages you receive from Zoom.  Add your logic to act on messages here
        
        Sample messages may want to take action on:
        
        content['payload']['object']['participant']['user_name']    # Username in the meeting 
        content['payload']['object']['participant']['leave_reason'] # The reason the user left the meeting
        content['event'])                                           # the event that generated the message. ie meeting.participant_left
        content['payload']['object']['topic']                       # the topic of the meeting 
        content['payload']['object']['id']                          # meeting id
        
    '''
    
    def process_message(self, message):
        j = json.loads(message) # load the message into json
        self.logger.info(j['module'] + " message received") # log the message
        print(str(datetime.datetime.now()) + " - " + j['module'] + " message received")
        print(json.dumps(j,indent=4))
        if (j['module'] == 'message'):
            content_string = j['content']  # load the message content into its own json object
            content = json.loads(content_string)
            
            if (content['event'] == "meeting.participant_left"):  # if a user left a meeting
                self.process_leave_event(content)
                
            if (content['event'] == "meeting.ended"):             # if a meeting ended
                self.process_meeting_end_event(content) 

            if (content['event'] == "meeting.participant_joined"):             # if a participant joined a meeting
                self.process_participant_joined_event(content)  
                
        elif (j['module'] == 'heartbeat'):  # if a heartbeat is received
            self.logger.info("Received heartbeat response.  Success = " + str(j['success']))
            print(str(datetime.datetime.now()) + " - Received heartbeat response.  Success = " + str(j['success']))


    def process_leave_event(self, content):
        print(content['payload']['object']['participant']['user_name'] + " has left the meeting " + content['payload']['object']['topic'] + "!")
        self.logger.info(content['payload']['object']['participant']['user_name'] + " has left the meeting " + content['payload']['object']['topic'] + "!")
        
        #Take what ever action you want here, for example send an email
        
        email_msg = content['payload']['object']['participant']['user_name'] + " has left the meeting " + content['payload']['object']['topic'] + "!"
        self.send_mail(to_email=['youremailaddress@domain.com'],
            subject="A user has left the meeting!", message=email_msg)
    
    def process_meeting_end_event(self, content):
        print(content['payload']['object']['id'] + " has ended!")
        self.logger.info(content['payload']['object']['id'] + " has ended!")
        #Take what ever action you want here
            
    def process_participant_joined_event(self, content):
        print(content['payload']['object']['participant']['user_name'] + " has joined the meeting " + content['payload']['object']['topic'] + "!")
        self.logger.info(content['payload']['object']['participant']['user_name'] + " has joined the meeting " + content['payload']['object']['topic'] + "!")
        
        #Take what ever action you want here like, for example use the Zoom API to place a call out to another participant
        self.place_call(str(content['payload']['object']['id']), "Bob", "enter_phone_number")
    
    ''' 
        on_message(self, ws, message)
        function that is called when a mesage is received on the WebSocket
    '''
    
    def on_message(self, ws, message):
        self.process_message(message) 
        
    ''' 
        on_error(self, ws, error)
        function that is called when an is received on the WebSocket
    '''
    
    def on_error(self, ws, error):
        print(f"Encountered error: {error}")
        self.logger.info("Encountered error: " + str(error))
        
    ''' 
        on_close(self, ws, message)
        function that is called when the WebSocket is closed
    '''
    
    def on_close(self, ws, close_status_code, close_msg):
        print("Connection closed")
        
    ''' 
        on_open(self, ws)
        function that is called when the WebSocket is opened
    '''
    
    def on_open(self, ws):
        print("Connection opened")
        def send_heartbeat(*args):  # Inner function to send a WebSocket keep alive to Zoom
            while True:
                time.sleep(20)  # interval to send heartbeats to keep the connection active
                ws.send('{ "module": "heartbeat"  }')
                self.logger.info("ZoomWebSocket sent heartbeat to Zoom")
                    
        thread.start_new_thread(send_heartbeat,()) # Start a thread who's job in life is to send heartbeats to Zoom
        
    def place_call(self, meeting_ID, name, phone_number):

        meeting_options = { "method": "participant.invite.callout",
                        "params": {
                        "invitee_name": str(name),
                        "phone_number": str(phone_number),
                        "invite_options": {
                            "require_greeting": False,
                               "require_pressing_one": False
                            },
                        }
                       }
  
        headers = {'authorization': 'Bearer ' + self.ACCESS_TOKEN,
               'content-type': 'application/json'}
        URL = 'https://api.zoom.us/v2/live_meetings/' + str(meeting_ID) + '/events'
    
        print ("Placing call to " + str(phone_number) + " to join " + str(name) + " to meeting id " + str(meeting_ID))
        self.logger.info("Placing call to " + str(phone_number) + " to join " + str(name) + " to meeting id " + str(meeting_ID))
        r = requests.patch(URL, headers=headers, data=json.dumps(meeting_options))
        print(r.text)
        
        print("Place call request returned " + str(r)) 
        self.logger.info("Place call request returned " + str(r))
          
    '''
        send_mail() sends an email 
    
        :param:   to_email - email address to send message to
        :param:   subject - subject of the email being sent
        :param:   message - the message to send
        :param:   server - the SMTP server to relay message
        :return:  None
    '''
    def send_mail(self,to_email, subject, message, server='enter_ip_address_of_smtp_relay',
              from_email='FromEmail@domain.com'):
        # import smtplib
        msg = EmailMessage()
        msg['Subject'] = subject
        msg['From'] = from_email
        msg['To'] = ', '.join(to_email)
        msg.set_content(message)
        print(msg)
        server = smtplib.SMTP(server)
        server.set_debuglevel(1)
        server.send_message(msg)
        server.quit()
        print('successfully sent the mail.') 
    
    '''
        run(self)
        Starts the websocket and listens to messages
    '''
    def run(self):
        def refresh_expired_token(*args):   #Inner function to refresh the Zoom API access token which expires every hour
            while True:
                time.sleep(3500)  # how often to refresh. Zoom access token expires every hour(3600 seconds) using 3500 seconds to allow some time for delays
                self.get_access_token()
                self.logger.info("Access token expired, fetching new token")
                print("Access token expired, fetching new token")
            
        thread.start_new_thread(refresh_expired_token,()) # start a new thread who's job in life is to refresh the Zoom Access token based on the sleep timer
        
        websocket.enableTrace(False)
        ws = websocket.WebSocketApp("wss://ws.zoom.us/ws?subscriptionId=blahblahblah&access_token="+str(zws.ACCESS_TOKEN),		#your wss url 
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close)
        
        ws.run_forever(dispatcher=rel, reconnect=5)  # Set dispatcher to automatic reconnection, 5 second reconnect delay if connection closed unexpectedly
        rel.signal(2, rel.abort)  # Keyboard Interrupt
        rel.dispatch()
        
       
# main       
if __name__ == "__main__":
    zws = ZoomWebSocket()  # make an instance of the class and run it
    zws.run()
  
    
    
    
    


