# email_sender.py (with SMTP Debugging)
import json
import logging
import pyodbc
import boto3
import smtplib
from botocore.exceptions import ClientError
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# --- Configuration & Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def get_secrets():
    """Retrieves all necessary secrets from AWS Secrets Manager."""
    secret_name = "nelcm-db"
    region_name = "us-east-1"
    session = boto3.session.Session()
    client = session.client(service_name='secretsmanager', region_name=region_name)
    try:
        logger.info("Attempting to retrieve secrets...")
        get_secret_value_response = client.get_secret_value(SecretId=secret_name)
        secret_string = get_secret_value_response['SecretString']
        secrets = json.loads(secret_string)
        logger.info("Successfully retrieved secrets.")
        return secrets
    except ClientError as e:
        logger.error(f"Failed to retrieve secret '{secret_name}': {e}")
        raise e


def send_renewal_email_smtp(secrets, recipient_email, member_name, expiration_date):
    SENDER_NAME = "The Childrens Museum"
    SENDER_EMAIL = "nelcm98@gmail.com"
    SMTP_HOST = "vpce-0f5b358e20d5e0339-0wws8voj.email-smtp.us-east-1.vpce.amazonaws.com"
    SMTP_PORT = 587

    SMTP_USER = secrets.get('smtp_user')
    SMTP_PASS = secrets.get('smtp_password')

    if not SMTP_USER or not SMTP_PASS:
        logger.error("SMTP username or password not found in secrets.")
        return False
    
    logger.info(f"Connecting to SMTP_HOST: '{SMTP_HOST}' on port {SMTP_PORT}")

    SUBJECT = "Your Children's Museum Membership Is Expiring Soon!"
    BODY_HTML = f"""
    <html><head></head><body>
      <h2>Time to Renew Your Membership!</h2>
      <p>Dear {member_name},</p>
      <p>This is a friendly reminder that your family's membership is scheduled to expire on 
        <b>{expiration_date.strftime('%B %d, %Y')}</b>.</p>
      <p>Renewing is easy! Simply visit our front desk on your next visit.</p>
      <p>We look forward to seeing you again soon!</p><br>
      <p>Sincerely,</p><p><b>The Children's Museum Team</b></p>
    </body></html>
    """

    msg = MIMEMultipart('alternative')
    msg['Subject'] = SUBJECT
    msg['From'] = f"{SENDER_NAME} <{SENDER_EMAIL}>"
    msg['To'] = recipient_email
    msg.attach(MIMEText(BODY_HTML, 'html'))

    server = None
    try:
        logger.info("Initializing SMTP_SSL client for port 465...")
        server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=10)
        logger.info("Setting debug level to 1...")
        server.set_debuglevel(1)
        
        # The starttls() call is removed because the connection is already secure.
        
        logger.info("Attempting server.login()...")
        server.login(SMTP_USER, SMTP_PASS)

        logger.info("Attempting server.sendmail()...")
        server.sendmail(SENDER_EMAIL, [recipient_email], msg.as_string())
        logger.info(f"Successfully sent email to {recipient_email}.")
        return True
    except Exception as e:
        logger.error(f"SMTP email failed to send to {recipient_email}: {e}")
        return False
    finally:
        if server:
            logger.info("Closing SMTP server connection.")
            server.quit()

# --- Lambda Handler (No changes needed below this line) ---
def handler(event, context):
    logger.info("Email sender handler started.")
    
    conn = None
    try:
        all_secrets = get_secrets()
        db_password = all_secrets['password']

        logger.info("Attempting to connect to the database...")
        conn = pyodbc.connect(
            driver='/var/task/lib/libmsodbcsql-18.4.so.1.1',
            server='nelcm.cy1ogm8uwbvo.us-east-1.rds.amazonaws.com,1433',
            database='nelcm',
            uid='nelcm',
            pwd=db_password,
            Encrypt='yes',
            TrustServerCertificate='yes',
            timeout=5
        )
        logger.info("Database connection successful.")
        cursor = conn.cursor()

        for record in event['Records']:
            try:
                message_body = json.loads(record['body'])
                member_id, email, name = message_body['member_id'], message_body['email'], message_body['name']
                last_name, expires_str = message_body['last_name'], message_body['expires']
                expires = datetime.strptime(expires_str, '%Y-%m-%d').date()

                logger.info(f"Processing renewal for {name} {last_name} (ID: {member_id})")

                email_sent = send_renewal_email_smtp(all_secrets, email, f"{name} {last_name}", expires)

                if email_sent:
                    logger.info(f"Attempting to update database flag for member ID {member_id}...")
                    cursor.execute("UPDATE family SET renewal_email_sent = 1 WHERE member_id = ?", member_id)
                    conn.commit()
                    logger.info(f"Successfully updated flag for {member_id}.")
                else:
                    logger.error(f"Skipping database update for {member_id} because email failed.")

            except Exception as e:
                logger.error(f"Error processing a message: {e}")
                if conn: conn.rollback()
                continue
                
        cursor.close()
        
    except Exception as e:
        logger.error(f"A critical error occurred in the handler: {e}")
        raise e
    finally:
        if conn:
            conn.close()
            logger.info("Database connection closed.")

    logger.info("Email sender handler finished successfully.")
    return {'statusCode': 200, 'body': json.dumps('Processing complete.')}