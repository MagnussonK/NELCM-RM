# email_sender.py
import json
import logging
import pyodbc
import boto3
from botocore.exceptions import ClientError

# --- Configuration & Logging (copied from app.py) ---
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

def send_renewal_email_ses(recipient_email, member_name, expiration_date):
    SENDER = "The Childrens Museum <nelcm98@gmail.com>"
    AWS_REGION = "us-east-1"
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
        logger.info(f"Email sent successfully to {recipient_email}! Message ID: {response['MessageId']}")
        return True
    except ClientError as e:
        logger.error(f"Email failed to send to {recipient_email}: {e.response['Error']['Message']}")
        return False

# --- Lambda Handler ---
def handler(event, context):
    """
    This handler is triggered by messages from the SQS queue.
    It processes each message to send a renewal email and update the database.
    """
    conn = get_db_connection()
    if conn is None:
        logger.error("Could not connect to the database. Aborting.")
        # Re-raise the error to ensure the message is not deleted from the queue
        raise ConnectionError("Database connection failed.")

    cursor = conn.cursor()

    for record in event['Records']:
        try:
            # The message body is a JSON string, so it needs to be parsed
            message_body = json.loads(record['body'])
            
            member_id = message_body['member_id']
            email = message_body['email']
            name = message_body['name']
            last_name = message_body['last_name']
            
            # The date is a string, so convert it back to a date object
            from datetime import datetime
            expires = datetime.strptime(message_body['expires'], '%Y-%m-%d').date()

            logger.info(f"Processing renewal for {name} {last_name} (ID: {member_id})")

            # 1. Send the email
            email_sent = send_renewal_email_ses(
                recipient_email=email,
                member_name=f"{name} {last_name}",
                expiration_date=expires
            )

            # 2. If the email was sent successfully, update the database
            if email_sent:
                update_query = "UPDATE family SET renewal_email_sent = 1 WHERE member_id = ?"
                cursor.execute(update_query, member_id)
                conn.commit()
                logger.info(f"Successfully updated renewal_email_sent flag for member ID {member_id}.")
            else:
                logger.error(f"Skipping database update for {member_id} because email failed to send.")

        except Exception as e:
            logger.error(f"An error occurred processing a message: {e}")
            conn.rollback()
            # If an error occurs, the message will become visible in the queue again for a retry
            # It's important to continue processing other messages in the batch
            continue 
            
    # Close the database connection after processing the batch
    cursor.close()
    conn.close()

    return {
        'statusCode': 200,
        'body': json.dumps('Email processing complete.')
    }