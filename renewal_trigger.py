# renewal_trigger.py
import pyodbc
import json
from datetime import date
import logging
import os

import boto3
from botocore.exceptions import ClientError

# --- Configuration & Helper Functions (Copied from app.py for standalone execution) ---

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
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
            driver='/var/task/lib/libmsodbcsql-18.4.so.1.1',
            server='nelcm.cy1ogm8uwbvo.us-east-1.rds.amazonaws.com,1433',
            database='nelcm',
            uid='nelcm',
            pwd=db_password,
            Encrypt='yes',
            TrustServerCertificate='yes'
        )
        logger.info("Database connection established successfully.")
        return conn
    except pyodbc.Error as ex:
        logger.error(f"DATABASE CONNECTION FAILED: {ex}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred during DB connection: {e}")
        return None

# --- Lambda Handler ---

def handler(event, context):
    """
    Lambda handler triggered by a schedule.
    Resets the renewal_email_sent to 0 for any family whose membership
    expires in the current month.
    """
    logger.info("Starting monthly renewal flag reset process...")
    conn = None
    cursor = None
    
    try:
        conn = get_db_connection()
        if conn is None:
            raise ConnectionError("Failed to establish a database connection.")

        cursor = conn.cursor()
        
        today = date.today()
        current_month = today.month
        current_year = today.year
        
        logger.info(f"Checking for memberships expiring in {current_month}/{current_year}.")
        
        # SQL query to update the flag for members expiring this month and year.
        sql_query = """
            UPDATE family
            SET renewal_email_sent = 0
            WHERE
                MONTH(membership_expires) = ? AND
                YEAR(membership_expires) = ?
        """
        
        cursor.execute(sql_query, current_month, current_year)
        conn.commit()
        
        updated_rows = cursor.rowcount
        success_message = f"Successfully reset renewal_email_sent for {updated_rows} records expiring in {current_month}/{current_year}."
        logger.info(success_message)
        
        return {
            'statusCode': 200,
            'body': json.dumps({'message': success_message, 'updated_records': updated_rows})
        }

    except pyodbc.Error as ex:
        sqlstate = ex.args[0]
        error_message = f"Database error during renewal flag update: {sqlstate} - {ex}"
        logger.error(error_message)
        if conn:
            conn.rollback()
        return {
            'statusCode': 500,
            'body': json.dumps({'error': error_message})
        }
    except Exception as e:
        error_message = f"An unexpected error occurred: {e}"
        logger.error(error_message)
        if conn:
            conn.rollback()
        return {
            'statusCode': 500,
            'body': json.dumps({'error': error_message})
        }
    finally:
        if cursor:
            cursor.close()
            logger.info("Database cursor closed.")
        if conn:
            conn.close()
            logger.info("Database connection closed.")