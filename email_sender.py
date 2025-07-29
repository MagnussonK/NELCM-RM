# email_sender.py
import json
import logging
import pyodbc
import boto3
from botocore.exceptions import ClientError
from datetime import datetime

# --- Configuration & Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def get_database_password():
    secret_name = "nelcm-db"
    region_name = "us-east-1"
    session = boto3.session.Session()
    client = session.client(service_name='secretsmanager', region_name=region_name)
    try:
        get_secret_value_response = client.get_secret_value(SecretId=secret_name)
        secret_string = get_secret_value_response['SecretString']
        secret_data = json.loads(secret_string)
        return secret_data['password']
    except ClientError as e:
        logger.error(f"Failed to retrieve secret '{secret_name}': {e}")
        raise e

def get_db_connection():
    try:
        db_password = get_database_password()
        conn = pyodbc.connect(
            driver='/var/task/lib/libmsodbcsql-18.4.so.1.1',
            server='nelcm.cy1ogm8uwbvo.us-east-1.rds.amazonaws.com,1433',
            database='nelcm',
            uid='nelcm',
            pwd=db_password,
            Encrypt='yes',
            TrustServerCertificate='yes'
        )
        return conn
    except pyodbc.Error as ex:
        logger.error(f"DATABASE CONNECTION FAILED: {ex}")
        return None

def send_email(recipient_email, member_name, email_type, data={}):
    """
    Sends an email using AWS SES based on the specified email type.
    """
    SENDER = "The Childrens Museum <nelcm98@gmail.com>"
    AWS_REGION = "us-east-1"
    SUBJECT = ""
    BODY_HTML = ""

    # --- Determine Email Content Based on Type ---
    if email_type == 'renewal_reminder':
        expiration_date = data.get('expiration_date')
        if not expiration_date:
            logger.error("Expiration date missing for renewal reminder.")
            return False
        
        SUBJECT = "Your Children's Museum Membership Is Expiring Soon!"
        BODY_HTML = f"""
        <html><head></head><body>
          <h2>Time to Renew Your Membership!</h2>
          <p>Dear {member_name},</p>
          <p>This is a friendly reminder that your family's membership is scheduled to expire on 
            <b>{expiration_date.strftime('%B %d, %Y')}</b>.</p>
          <p>Renewing is easy! Simply visit our front desk on your next visit to continue your adventure with us.</p>
          <p>We look forward to seeing you again soon!</p><br>
          <p>Sincerely,</p><p><b>The Children's Museum Team</b></p>
        </body></html>
        """
    elif email_type == 'welcome':
        SUBJECT = "Welcome to The Children's Museum!"
        BODY_HTML = f"""
        <html><head></head><body>
          <h2>Welcome to the Family!</h2>
          <p>Dear {member_name},</p>
          <p>We are so excited to have you as a new member of The Children's Museum. 
             Your membership is your ticket to a year of exploration, imagination, and fun!</p>
          <p>We can't wait to see you soon!</p><br>
          <p>Sincerely,</p><p><b>The Children's Museum Team</b></p>
        </body></html>
        """
    elif email_type == 'renewal_thank_you':
        SUBJECT = "Thank You for Renewing Your Membership!"
        BODY_HTML = f"""
        <html><head></head><body>
          <h2>Thank You For Your Support!</h2>
          <p>Dear {member_name},</p>
          <p>Thank you for renewing your membership with The Children's Museum! 
             Your continued support helps us provide a creative and educational space for children in our community. 
             We're thrilled to have you with us for another year of adventure.</p>
          <p>Get ready for more fun!</p><br>
          <p>Sincerely,</p><p><b>The Children's Museum Team</b></p>
        </body></html>
        """
    else:
        logger.error(f"Unknown email type: '{email_type}'. Cannot send email.")
        return False

    # --- Send Email via SES ---
    ses_client = boto3.client('ses', region_name=AWS_REGION)
    try:
        response = ses_client.send_email(
            Source=SENDER,
            Destination={'ToAddresses': [recipient_email]},
            Message={
                'Body': {'Html': {'Charset': "UTF-8", 'Data': BODY_HTML}},
                'Subject': {'Charset': "UTF-8", 'Data': SUBJECT},
            },
            ConfigurationSetName='nelcm-transactional-config'
        )
        logger.info(f"Email ('{email_type}') sent successfully to {recipient_email}! Message ID: {response['MessageId']}")
        return True
    except ClientError as e:
        logger.error(f"Email ('{email_type}') failed to send to {recipient_email}: {e.response['Error']['Message']}")
        return False

# --- Lambda Handler ---
def handler(event, context):
    """
    This handler is triggered by messages from the SQS queue.
    It processes each message to send an email based on its type and updates the database if necessary.
    """
    conn = get_db_connection()
    if conn is None:
        logger.error("Could not connect to the database. Aborting.")
        raise ConnectionError("Database connection failed.")

    cursor = conn.cursor()

    for record in event['Records']:
        try:
            message_body = json.loads(record['body'])
            
            email_type = message_body.get('email_type', 'unknown')
            member_id = message_body.get('member_id')
            email = message_body.get('email')
            name = message_body.get('name')
            last_name = message_body.get('last_name')

            if not all([email, name, last_name]):
                logger.error(f"Message is missing required fields (email, name, last_name). Skipping. Body: {message_body}")
                continue

            logger.info(f"Processing '{email_type}' email for {name} {last_name}")

            email_data = {}
            if email_type == 'renewal_reminder':
                # The date is a string, so convert it back to a date object
                expires_str = message_body.get('expires')
                if not expires_str:
                    logger.error("Renewal reminder is missing 'expires' date. Skipping.")
                    continue
                email_data['expiration_date'] = datetime.strptime(expires_str, '%Y-%m-%d').date()

            # 1. Send the appropriate email
            email_sent = send_email(
                recipient_email=email,
                member_name=f"{name} {last_name}",
                email_type=email_type,
                data=email_data
            )

            # 2. If email sent, perform type-specific database actions
            if email_sent:
                if email_type == 'renewal_reminder':
                    update_query = "UPDATE family SET renewal_email_sent = 1 WHERE member_id = ?"
                    cursor.execute(update_query, member_id)
                    conn.commit()
                    logger.info(f"Successfully updated renewal_email_sent flag for member ID {member_id}.")
                else:
                    logger.info(f"Email type '{email_type}' sent for member {member_id}. No DB update needed.")
            else:
                logger.error(f"Skipping database actions for {member_id} because email failed to send.")

        except Exception as e:
            logger.error(f"An error occurred processing a message: {e}")
            conn.rollback()
            # It's important to continue processing other messages in the batch
            continue 
            
    # Close the database connection after processing the batch
    cursor.close()
    conn.close()

    return {
        'statusCode': 200,
        'body': json.dumps('Email processing complete.')
    }