# ses_handler.py
import json
import logging
import pyodbc
import boto3
from botocore.exceptions import ClientError

# --- Configuration & Helper Functions (Copied from app.py) ---

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def get_database_password():
    """Retrieves the database password from AWS Secrets Manager."""
    secret_name = "nelcm-db"
    region_name = "us-east-1"
    session = boto3.session.Session()
    client = session.client(service_name='secretsmanager', region_name=region_name)
    try:
        get_secret_value_response = client.get_secret_value(SecretId=secret_name)
    except ClientError as e:
        logger.error(f"Failed to retrieve secret '{secret_name}': {e}")
        raise e
    secret_string = get_secret_value_response['SecretString']
    secret_data = json.loads(secret_string)
    return secret_data['password']

def get_db_connection():
    """Establishes a connection to the SQL Server database."""
    try:
        db_password = get_database_password()
        conn = pyodbc.connect(
            #driver='/var/task/lib/libmsodbcsql-18.4.so.1.1',
            driver = '{ODBC Driver 18 for SQL Server}'
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

def remove_email_from_database(email):
    """Connects to the DB and sets the email field to NULL for the given address."""
    logger.info(f"Attempting to remove email: {email}")
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        if conn is None:
            raise ConnectionError("Failed to establish a database connection for email removal.")
        
        cursor = conn.cursor()
        # Update the family table to remove the email address from the primary member
        sql_query = "UPDATE family SET email = NULL WHERE email = ?"
        
        cursor.execute(sql_query, email)
        conn.commit()
        
        updated_rows = cursor.rowcount
        if updated_rows > 0:
            logger.info(f"Successfully removed email '{email}' for {updated_rows} record(s).")
        else:
            logger.warning(f"No records found with email '{email}' to remove.")
            
    except Exception as e:
        logger.error(f"An error occurred while removing email {email}: {e}")
        if conn:
            conn.rollback()
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

# --- Lambda Handler ---

def handler(event, context):
    """
    Lambda handler for processing SES bounce and complaint notifications from SNS.
    """
    logger.info("Received event from SNS")
    
    for record in event['Records']:
        sns_message_str = record['Sns']['Message']
        message = json.loads(sns_message_str)
        notification_type = message.get('notificationType')
        
        emails_to_remove = []

        if notification_type == 'Bounce':
            bounce = message.get('bounce', {})
            # Process only permanent (hard) bounces
            if bounce.get('bounceType') == 'Permanent':
                for recipient in bounce.get('bouncedRecipients', []):
                    emails_to_remove.append(recipient.get('emailAddress'))
                logger.info(f"Processing permanent bounce for: {emails_to_remove}")

        elif notification_type == 'Complaint':
            for recipient in message.get('complaint', {}).get('complainedRecipients', []):
                emails_to_remove.append(recipient.get('emailAddress'))
            logger.info(f"Processing complaint (unsubscribe) for: {emails_to_remove}")

        # For each collected email, call the function to remove it from the DB
        for email in emails_to_remove:
            if email:
                remove_email_from_database(email)

    return {
        'statusCode': 200,
        'body': json.dumps('SES event processing complete.')
    }