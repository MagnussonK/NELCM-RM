# email_sender.py
import json
import logging
import pyodbc
import boto3
from botocore.exceptions import ClientError
from datetime import datetime
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# --- Configuration & Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# --- AWS Configuration ---
AWS_REGION = "us-east-1"
SES_SMTP_HOST = "email-smtp.us-east-1.amazonaws.com"
SES_SMTP_PORT = 465 # Port for SMTPS (SSL/TLS)

def get_secret(secret_name):
    """Generic function to retrieve a secret from AWS Secrets Manager."""
    session = boto3.session.Session()
    client = session.client(service_name='secretsmanager', region_name=AWS_REGION)
    try:
        get_secret_value_response = client.get_secret_value(SecretId=secret_name)
        secret_string = get_secret_value_response['SecretString']
        return json.loads(secret_string)
    except ClientError as e:
        logger.error(f"Failed to retrieve secret '{secret_name}': {e}")
        raise e

def get_db_connection():
    """Establishes a connection to the SQL Server database."""
    try:
        db_secret = get_secret("nelcm-db")
        conn = pyodbc.connect(
            driver='/var/task/lib/libmsodbcsql-18.4.so.1.1',
            server='nelcm.cy1ogm8uwbvo.us-east-1.rds.amazonaws.com,1433',
            database='nelcm',
            uid='nelcm',
            pwd=db_secret['password'],
            Encrypt='yes',
            TrustServerCertificate='yes'
        )
        return conn
    except pyodbc.Error as ex:
        logger.error(f"DATABASE CONNECTION FAILED: {ex}")
        return None

def send_email_smtp(recipient_email, member_name, email_type, data={}):
    """
    Sends an email using the SMTP protocol over port 465.
    """
    SENDER_EMAIL = "Northeast Louisiana Childrens Museum <nelcm98@gmail.com>"
    SUBJECT = ""
    BODY_HTML = ""

    # --- Determine Email Content Based on Type ---
    if email_type == 'renewal_reminder':
        expiration_date = data.get('expiration_date')
        if not expiration_date:
            logger.error("Expiration date missing for renewal reminder.")
            return False
        
        SUBJECT = "Your Northeast Louisiana Children's Museum Membership Is Expiring Soon!"
        BODY_HTML = f"""
        <html><head></head><body>
          <h2>Time to Renew Your Membership!</h2>
          <p>Dear {member_name},</p>
          <p>This is a friendly reminder that your family's membership is scheduled to expire on 
            <b>{expiration_date.strftime('%B %d, %Y')}</b>.</p>
          <p>Renewing is easy! Simply visit our front desk on your next visit to continue your adventure with us.</p>
          <p>We look forward to seeing you again soon!</p><br>
          <p>Sincerely,</p><p><b>Northeast Louisiana Children's Museum Team</b></p>
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
          <p>Sincerely,</p><p><b>Northeast Louisiana Children's Museum Team</b></p>
        </body></html>
        """
    elif email_type == 'renewal_thank_you':
        SUBJECT = "Thank You for Renewing Your Membership!"
        BODY_HTML = f"""
        <html><head></head><body>
          <h2>Thank You For Your Support!</h2>
          <p>Dear {member_name},</p>
          <p>Thank you for renewing your membership with Northeast Louisiana Children's Museum! 
             Your continued support helps us provide a creative and educational space for children in our community. 
             We're thrilled to have you with us for another year of adventure!</p>
          <p>Get ready for more fun!</p><br>
          <p>Sincerely,</p><p><b>Northeast Louisiana Children's Museum Team</b></p>
        </body></html>
        """
    else:
        logger.error(f"Unknown email type: '{email_type}'. Cannot send email.")
        return False

    # --- Get SMTP Credentials from the combined 'nelcm-db' secret ---
    try:
        # Fetch the combined database secret
        secret_data = get_secret("nelcm-db")
        # Use the correct keys as shown in the screenshot
        SMTP_USERNAME = secret_data['smtp_user']
        SMTP_PASSWORD = secret_data['smtp_password']
    except Exception as e:
        logger.error(f"Could not retrieve SMTP credentials from Secrets Manager: {e}")
        return False

    # --- Construct the Email Message ---
    msg = MIMEMultipart('alternative')
    msg['Subject'] = SUBJECT
    msg['From'] = SENDER_EMAIL
    msg['To'] = recipient_email
    msg.attach(MIMEText(BODY_HTML, 'html'))

    # --- Send Email via SMTP_SSL ---
    try:
        context = ssl.create_default_context()
        logger.info(f"Connecting to SMTP server {SES_SMTP_HOST} on port {SES_SMTP_PORT}...")
        with smtplib.SMTP_SSL(SES_SMTP_HOST, SES_SMTP_PORT, context=context) as server:
            logger.info("Connection successful. Logging in...")
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            logger.info("Login successful. Sending email...")
            server.sendmail(SENDER_EMAIL, recipient_email, msg.as_string())
            logger.info(f"Email ('{email_type}') sent successfully to {recipient_email} via SMTP.")
        return True
    except Exception as e:
        logger.error(f"SMTP email failed to send to {recipient_email}: {e}")
        return False

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
                expires_str = message_body.get('expires')
                if not expires_str:
                    logger.error("Renewal reminder is missing 'expires' date. Skipping.")
                    continue
                email_data['expiration_date'] = datetime.strptime(expires_str, '%Y-%m-%d').date()

            # Call the SMTP email function
            email_sent = send_email_smtp(
                recipient_email=email,
                member_name=f"{name} {last_name}",
                email_type=email_type,
                data=email_data
            )

            if email_sent and email_type == 'renewal_reminder':
                update_query = "UPDATE family SET renewal_email_sent = 1 WHERE member_id = ?"
                cursor.execute(update_query, member_id)
                conn.commit()
                logger.info(f"Successfully updated renewal_email_sent flag for member ID {member_id}.")
            
        except Exception as e:
            logger.error(f"An error occurred processing a message: {e}")
            if conn:
                conn.rollback()
            continue 
            
    cursor.close()
    conn.close()

    return {
        'statusCode': 200,
        'body': json.dumps('Email processing complete.')
    }