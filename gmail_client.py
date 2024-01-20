import base64
import json
import os
import logging
import pickle

# import pytz
# import base64

from google.cloud import pubsub_v1
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

from icalendar import Calendar as iCalendar
# Remove the import statement for 'InstalledAppFlow'
# from google_auth_oauthlib.flow import InstalledAppFlow

# Get logging level from environment variable
logging_level = os.getenv("LOGGING_LEVEL", "INFO")

# Convert logging level to corresponding attribute of the logging module
logging_level = getattr(logging, logging_level.upper(), logging.INFO)

# Configure logging
logging.basicConfig(
    level=logging_level, format="%(asctime)s - %(levelname)s - %(message)s"
)

# TOKEN_FILE = "token.pickle"
# CREDENTIALS_FILE = "credentials.json"
CURRENT_HISTORY_ID = None

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.labels",
    "https://www.googleapis.com/auth/calendar",
]

GOOGLE_CALENDAR = os.getenv("GOOGLE_CALENDAR", "default")
ADD_TO_CALENDAR_LABEL_NAME = os.getenv("ADD_TO_CALENDAR_LABEL_NAME", "AddToCalendar")
ADD_TO_CALENDAR_LABEL_ID = None
LABEL_FILTERS = os.getenv("LABEL_FILTERS", None)
LABEL_FILTERS_ID_LIST = []
GOOGLE_AUTH_FLOW_PORT = os.getenv("GOOGLE_AUTH_FLOW_PORT", "8080")
CALENDAR_ID = None

DEFAULT_GMAIL_LABELS = [
    'CHAT', 'SENT', 'INBOX', 'IMPORTANT', 'TRASH', 'DRAFT', 'SPAM', 'CATEGORY_FORUMS', 'CATEGORY_UPDATES',
    'CATEGORY_PERSONAL', 'CATEGORY_PROMOTIONS', 'CATEGORY_SOCIAL', 'STARRED', 'UNREAD'
]


def get_credentials():
    creds = None
    token_pickle = os.getenv("TOKEN_PICKLE", "./credentials/token.pickle")
    # credentials_json = CREDENTIALS_FILE  # Path to your downloaded credentials file

    if os.path.exists(token_pickle):
        with open(token_pickle, "rb") as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # Define the path to the credentials file
            credentials_json = os.getenv("GMAIL_CALENDAR_CREDENTIALS")
            flow = InstalledAppFlow.from_client_secrets_file(credentials_json, SCOPES)
            logging.debug(
                "Running local server to get credentials on port "
                f"{GOOGLE_AUTH_FLOW_PORT}..."
            )
            port = 8080
            try:
                port = int(GOOGLE_AUTH_FLOW_PORT)
            except ValueError:
                # Handle the case where the environment variable value is not a valid integer
                print(
                    f"Environment variable value '{GOOGLE_AUTH_FLOW_PORT}' is not a valid integer. Using default 8080."
                )

            creds = flow.run_local_server(port=port)
        with open(token_pickle, "wb") as token:
            pickle.dump(creds, token)

    return creds


google_creds = get_credentials()


GMAIL_SERVICE = build("gmail", "v1", credentials=google_creds, cache_discovery=False)
CALENDAR_SERVICE = build(
    "calendar", "v3", credentials=google_creds, cache_discovery=False
)


def get_labels():
    try:
        logging.debug("Fetching GMAIL labels...")
        labels_response = GMAIL_SERVICE.users().labels().list(userId="me").execute()
        logging.debug(
            f"Successfully fetched GMAIL Labels - response: {labels_response}"
        )
        labels = labels_response.get("labels", [])
        filtered_labels = [label for label in labels if label["name"] not in DEFAULT_GMAIL_LABELS]
        gmail_label_id_names_dict = {label["id"]: label["name"] for label in filtered_labels}
        gmail_label_names_id_dict = {label["name"]: label["id"] for label in filtered_labels}
        return gmail_label_id_names_dict, gmail_label_names_id_dict
    except Exception as e:
        logging.error(f"Error fetching labels: {e}")
        return {}


gmail_label_id_names_dict, gmail_label_names_id_dict = get_labels()


def get_calendar_id(calendar_name):
    logging.debug(f"Fetching calendar with the name: {calendar_name}...")
    try:
        logging.debug("Fetching calendars...")
        calendars_result = CALENDAR_SERVICE.calendarList().list().execute()
        logging.debug(f"Successfully fetched calendars - response: {calendars_result}")
    except Exception as e:
        logging.error(f"Error fetching calendars: {e}")
        return None

    for calendar_entry in calendars_result["items"]:
        logging.debug(f"Calendar entry summary: {calendar_entry["summary"]}")
        if calendar_entry["summary"] == calendar_name:
            logging.debug(f"Found calendar with the name: {calendar_name} - id: {calendar_entry['id']}")
            return calendar_entry["id"]
    logging.error(f"No calendar found with the name: {calendar_name}")
    return None


def get_label_id(label_name):
    try:
        return gmail_label_names_id_dict[label_name]
    except Exception as e:
        logging.error(f"Error fetching labels: {e}")
        return None


def handle_attachments_and_update_calendar(history_id, message):
    message_id = message["id"]
    logging.info(f"HISTORY_ID #{history_id} - Handling attachments for message ID: {message_id}")

    try:
        message = GMAIL_SERVICE.users().messages().get(userId="me", id=message_id, format="full").execute()
        logging.info(f"HISTORY_ID #{history_id} - Retrieved message with ID: {message_id}")

        # Check if the message has parts in its payload
        if "parts" in message["payload"]:
            for part in message["payload"]["parts"]:
                if "attachmentId" in part["body"]:
                    attachment_id = part["body"]["attachmentId"]
                    logging.debug(f"HISTORY_ID #{history_id} - Found attachment with ID: {attachment_id}")
                    attachments = GMAIL_SERVICE.users().messages().attachments()
                    file_data = attachments.get(userId="me", messageId=message_id, id=attachment_id).execute()
                    logging.debug(f"HISTORY_ID #{history_id} - Retrieved attachment data for ID: {attachment_id}")

                    file_data = file_data["data"]
                    file_content = base64.urlsafe_b64decode(file_data.encode("UTF-8"))

                    cal = iCalendar.from_ical(file_content)
                    msg = f"HISTORY_ID #{history_id} - Parsed iCalendar data from attachment ID: {attachment_id}"
                    logging.debug(msg)

                    for component in cal.walk():
                        if component.name == "VEVENT":
                            summary = str(component.get("summary"))
                            dtstart = component.get("dtstart").dt
                            dtend = component.get("dtend").dt
                            logging.debug(
                                f"HISTORY_ID #{history_id} - Found VEVENT in calendar: Summary: {summary}, "
                                f"Start: {dtstart}, End: {dtend}"
                            )

                            event = {
                                "summary": summary,
                                "start": {"dateTime": dtstart.isoformat()},
                                "end": {"dateTime": dtend.isoformat()},
                            }

                            # Create or update the event
                            CALENDAR_SERVICE.events().insert(calendarId=CALENDAR_ID, body=event).execute()
                            logging.info(f"HISTORY_ID #{history_id} - Event created/updated in calendar: {summary}")
        else:
            logging.info(f"HISTORY_ID #{history_id} - No attachments found in message ID: {message_id}")

    except Exception as e:
        logging.error(f"HISTORY_ID #{history_id} - Error handling attachments for message ID: {message_id}: {e}")


def has_filter_labels(message, history_id):
    if any(label in LABEL_FILTERS_ID_LIST for label in message['labelIds']):
        logging.debug(
            f"HISTORY_ID #{history_id} - MESSAGE_ID #{message['id']} has "
            f"{ADD_TO_CALENDAR_LABEL_NAME} Label ID {ADD_TO_CALENDAR_LABEL_ID}"
        )

        return True

    logging.debug(
        f"HISTORY_ID #{history_id} - MESSAGE_ID #{message['id']} does not have any of the labels "
        "in LABEL_FILTERS_ID_LIST. "
    )
    return False


def has_add_to_calendar_label(message, history_id, labels):
    if ADD_TO_CALENDAR_LABEL_ID not in labels:
        logging.debug(
            f"HISTORY_ID #{history_id} - MESSAGE_ID #{message['id']} does not have "
            f"{ADD_TO_CALENDAR_LABEL_NAME} (Label ID {ADD_TO_CALENDAR_LABEL_ID}). Skiping..."
        )
        return False
    return True


def process_change(change, history_id):
    change_id = change["id"]
    logging.debug(f"HISTORY_ID #{history_id} - Processing CHANGE_ID #{change_id}")

    if "labelsAdded" not in change:
        return
    logging.debug(f"HISTORY_ID #{history_id} - change includes 'labelsAdded'")

    for label_info in change["labelsAdded"]:
        labels = label_info["labelIds"]
        logging.debug(f"HISTORY_ID #{history_id} - Label Info {label_info}")
        logging.debug(f"HISTORY_ID #{history_id} - Labels {labels}")

        message = label_info["message"]

        if has_add_to_calendar_label(message, history_id, labels) and has_filter_labels(message, history_id):
            handle_attachments_and_update_calendar(history_id, message)


def pubsub_to_dict(message):
    message_data = message.data.decode("utf-8")
    logging.debug(f"Message data: {message_data}")
    return json.loads(message_data)


def fetch_changes(pubsub_dict):
    email_address = pubsub_dict["emailAddress"]
    history_id = pubsub_dict["historyId"]
    try:
        logging.debug(f"HISTORY_ID #{history_id} - Fetching changes...")
        changes = GMAIL_SERVICE.users().history().list(
            userId=email_address,
            startHistoryId=CURRENT_HISTORY_ID
        ).execute().get("history", [])
        logging.debug(f"HISTORY_ID #{history_id} - Fetched {len(changes)} changes")
        return changes
    except Exception as e:
        logging.error(f"HISTORY_ID #{history_id} - Failed to fetch changes: {e}")
        return None


def message_callback(message):
    try:
        logging.debug(f"Acking Pub/Sub message:\n{message}...")
        message.ack()  # Acknowledge the message
        logging.debug(f"Pub/Sub message Acked Successfull:\n{message}...")
    except Exception as e:
        logging.error(f"Error acking Pub/Sub message: {e}")
        return

    pubsub_dict = pubsub_to_dict(message)
    email_address = pubsub_dict["emailAddress"]
    history_id = pubsub_dict["historyId"]

    if not email_address or not history_id:
        logging.error(f"Invalid Pub/Sub message: both emaill_address and history_id required\n{message}")
        return

    changes = fetch_changes(pubsub_dict)
    if changes is None:
        return

    logging.debug(f"HISTORY_ID #{history_id} - Processing {len(changes)} changes.")
    for change in changes:
        try:
            process_change(change, history_id)
        except Exception as e:
            logging.error(f"HISTORY_ID #{history_id} - Error processing change: {e}")


def setup_pubsub_subscription(project_id, subscription_name):
    logging.debug("Setting up Pub/Sub subscription...")

    subscriber = pubsub_v1.SubscriberClient()
    subscription_path = subscriber.subscription_path(project_id, subscription_name)

    logging.info(f"Wating for messages on {subscription_path}...")
    streaming_pull_future = subscriber.subscribe(
        subscription_path, callback=message_callback
    )
    # logging.info(f"Subscribed to Pub/Sub topic: {subscription_path}")
    return streaming_pull_future


def initialize_gmail_watch(topic_name):
    # search gmail_label_names_id_dict on key LABEL to get its label_id
    label_id = gmail_label_names_id_dict[ADD_TO_CALENDAR_LABEL_NAME]

    logging.debug("Initializing Gmail watch...")
    request_body = {
        "labelIds": [label_id],
        "topicName": topic_name,
        "labelFilterBehavior": "INCLUDE",
    }
    try:
        response = GMAIL_SERVICE.users().watch(userId="me", body=request_body).execute()
        logging.debug("Gmail watch successfully initialized")

        return response["historyId"]  # Save this historyId
    except Exception as e:
        logging.error(f"Error initializing Gmail watch: {e}")
        raise


def get_pub_sub_variables_from_env():
    logging.debug("Loading environment variables...")

    project_id = os.getenv("GOOGLE_CLOUD_PROJECT_ID")
    subscription_name = os.getenv("GOOGLE_CLOUD_PUBSUB_SUBSCRIPTION_NAME")
    topic_name_string = os.getenv("GOOGLE_CLOUD_PUBSUB_TOPIC_NAME")
    topic_name = f"projects/{project_id}/topics/{topic_name_string}"
    label_names = os.getenv("GMAIL_LABEL_NAMES")

    if not all([project_id, subscription_name, topic_name_string]):
        error_message = (
            "Missing required environment variables. Please check your configuration. "
            f"project_id: {project_id}, subscription_name: {subscription_name}, "
            f"topic_name_string: {topic_name_string}:"
        )
        logging.error(error_message)
        raise EnvironmentError("Missing environment variables")

    return project_id, subscription_name, topic_name, label_names


def main():
    logging.info("Starting main process...")

    project_id, subscription_name, topic_name, label_names = get_pub_sub_variables_from_env()

    global CALENDAR_ID
    CALENDAR_ID = get_calendar_id(GOOGLE_CALENDAR)

    global ADD_TO_CALENDAR_LABEL_ID
    ADD_TO_CALENDAR_LABEL_ID = gmail_label_names_id_dict[ADD_TO_CALENDAR_LABEL_NAME]

    global LABEL_FILTERS_ID_LIST

    if LABEL_FILTERS is None:
        logging.error("Environment variable 'LABEL_FILTERS' is not initialized. Exiting...")
        return
    else:
        LABEL_FILTERS_LIST = LABEL_FILTERS.split(",")
        LABEL_FILTERS_ID_LIST = [gmail_label_names_id_dict[label] for label in LABEL_FILTERS_LIST]
        logging.debug(f"LABEL_FILTERS_ID_LIST: {LABEL_FILTERS_ID_LIST}")

    global CURRENT_HISTORY_ID
    CURRENT_HISTORY_ID = initialize_gmail_watch(topic_name)

    streaming_pull_future = setup_pubsub_subscription(project_id, subscription_name)

    try:
        streaming_pull_future.result()
    except KeyboardInterrupt:
        streaming_pull_future.cancel()
        logging.info("Streaming pull future cancelled, exiting...")
    except Exception as e:
        logging.error(f"Error in Pub/Sub subscriber: {e}")


if __name__ == "__main__":
    main()
