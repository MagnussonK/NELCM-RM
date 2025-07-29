# V2 - Corrected and Final
import pyodbc
from flask import Flask, request, jsonify
from flask_cors import CORS
import json
from datetime import date, datetime, timedelta
import logging
import calendar
import os
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError
from flask.json.provider import JSONProvider

# --- Robust JSON Handling ---
# This custom class teaches Flask how to handle special data types like dates
# and decimals, preventing the app from crashing during JSON conversion.
class CustomJSONProvider(JSONProvider):
    def dumps(self, obj, **kwargs):
        return json.dumps(obj, **kwargs, default=self.default)

    def loads(self, s, **kwargs):
        return json.loads(s, **kwargs)

    @staticmethod
    def default(o):
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        if isinstance(o, Decimal):
            return float(o)
        raise TypeError(f"Object of type {o.__class__.__name__} is not JSON serializable")

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- App Initialization ---
app = Flask(__name__)
# Apply the custom JSON provider to the app
app.json = CustomJSONProvider(app)
CORS(app)

# --- Database Configuration ---
SQL_SERVER_INSTANCE = 'nelcm.cy1ogm8uwbvo.us-east-1.rds.amazonaws.com,1433'
DATABASE_NAME = 'nelcm'
DATABASE_UID = 'nelcm'
#ODBC_DRIVER = '{ODBC Driver 18 for SQL Server}'
ODBC_DRIVER = '/var/task/lib/libmsodbcsql-18.4.so.1.1'


def get_database_password():
    """Retrieves the database password from AWS Secrets Manager."""
    secret_name = "nelcm-db"
    region_name = "us-east-1"
    session = boto3.session.Session()
    client = session.client(service_name='secretsmanager', region_name=region_name)
    try:
        get_secret_value_response = client.get_secret_value(SecretId=secret_name)
    except ClientError as e:
        # Log the actual error from AWS
        logging.error(f"Failed to retrieve secret '{secret_name}': {e}")
        # Return None instead of crashing
        return None
    secret_string = get_secret_value_response['SecretString']
    secret_data = json.loads(secret_string)
    return secret_data['password']

def get_db_connection():
    """Establishes a connection to the SQL Server database."""
    try:
        db_password = get_database_password()
        # If the password could not be retrieved, stop here.
        if db_password is None:
            logging.error("Database password could not be retrieved. Aborting connection.")
            return None

        # This connection now uses the direct path to the driver library for consistency.
        conn = pyodbc.connect(
            driver=ODBC_DRIVER,
            server=SQL_SERVER_INSTANCE,
            database=DATABASE_NAME,
            uid=DATABASE_UID,
            pwd=db_password,
            Encrypt='yes',
            TrustServerCertificate='yes'
        )
        logging.info("Database connection established successfully.")
        return conn
    except pyodbc.Error as ex:
        logging.error(f"DATABASE CONNECTION FAILED: {ex}")
        return None
    except Exception as e:
        logging.error(f"An unexpected error occurred during DB connection: {e}")
        return None

# --- API Endpoints ---

@app.route('/api/data', methods=['GET'])
def get_data():
    """
    Fetches all data by joining members and family tables.
    """
    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor()
    try:
        query = """
            SELECT
                m.member_id, m.name, m.last_name, m.phone, m.birthday, m.gender,
                m.primary_member, m.secondary_member,
                f.address, f.city, f.state, f.zip_code, f.email, f.founding_family,
                f.mem_start_date, f.membership_expires, f.active_flag, f.renewal_email_sent
            FROM
                members AS m
            JOIN
                family AS f ON m.member_id = f.member_id
        """
        cursor.execute(query)
        
        columns = [column[0] for column in cursor.description]
        # The CustomJSONProvider now handles data type conversion automatically.
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        
        return jsonify(rows)

    except pyodbc.Error as ex:
        sqlstate = ex.args[0]
        logging.error(f"Error fetching data: {sqlstate} - {ex}")
        return jsonify({"error": f"Database error: {ex}"}), 500
    except Exception as e:
        logging.error(f"An unexpected error occurred in get_data: {e}")
        return jsonify({"error": "An unexpected server error occurred."}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

# (The rest of your functions: /update_expired_memberships, /add_record, etc. remain the same)
# ... paste the rest of your endpoint functions here ...
@app.route('/api/update_expired_memberships', methods=['PUT'])
def update_expired_memberships():
    """
    Updates the active status of members in the family table whose memberships have expired.
    """
    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor()
    try:
        today_str = date.today().strftime('%Y-%m-%d')
        # This query now correctly targets the 'family' table and 'active_flag' column
        cursor.execute("""
            UPDATE family
            SET active_flag = 0
            WHERE membership_expires < ? AND founding_family = 0
        """, today_str)
        conn.commit()
        updated_rows = cursor.rowcount
        logging.info(f"Checked for expired memberships. Updated {updated_rows} records.")
        return jsonify({"message": f"Expired memberships updated successfully. {updated_rows} records affected."}), 200
    except pyodbc.Error as ex:
        sqlstate = ex.args[0]
        logging.error(f"Database error during expiry update: {sqlstate} - {ex}")
        return jsonify({"error": f"Database error: {ex}"}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route('/api/family/<int:family_id>/renew', methods=['POST'])
def renew_membership(family_id):
    """Renews a family's membership from a new start date."""
    data = request.get_json()
    new_start_date_str = data.get('new_start_date')

    if not new_start_date_str:
        return jsonify({"error": "new_start_date is a required field"}), 400

    try:
        # Calculate new expiration date (1 year from the new start)
        new_start_date = datetime.strptime(new_start_date_str, '%Y-%m-%d').date()
        expiration_date = new_start_date.replace(year=new_start_date.year + 1)
    except ValueError:
        return jsonify({"error": "Invalid date format. Use YYYY-MM-DD."}), 400

    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500

    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE family SET membership_expires = ? WHERE member_id = ?",
            expiration_date,
            family_id
        )
        conn.commit()
        logging.info(f"Membership for family ID {family_id} renewed. New expiration: {expiration_date.isoformat()}")
        return jsonify({
            "message": "Membership renewed successfully.",
            "new_expiration_date": expiration_date.isoformat()
        })
    except pyodbc.Error as ex:
        conn.rollback()
        logging.error(f"Membership renewal failed for family ID {family_id}: {ex}")
        return jsonify({"error": "Database error during membership renewal."}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/bulk_update_expiry_dates', methods=['PUT'])
def bulk_update_expiry_dates():
    """
    Updates the membership_expires date for all non-founding members.
    Sets it to the last day of the month, one year after the mem_start_date.
    """
    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor()
    try:
        cursor.execute("""
            UPDATE family
            SET membership_expires = EOMONTH(DATEADD(year, 1, mem_start_date))
            WHERE mem_start_date IS NOT NULL AND founding_family = 0
        """)
        conn.commit()
        updated_rows = cursor.rowcount
        logging.info(f"Bulk updated membership_expires for {updated_rows} records.")
        return jsonify({"message": f"Successfully updated membership expiration dates for {updated_rows} records."}), 200
    except pyodbc.Error as ex:
        conn.rollback()
        sqlstate = ex.args[0]
        logging.error(f"Database error during bulk expiry date update: {sqlstate} - {ex}")
        return jsonify({"error": f"Database error: {ex}"}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route('/api/add_record', methods=['POST'])
def add_record():
    """
    Adds a new primary member record, creating entries in both members and family tables.
    """
    data = request.json
    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500
    
    cursor = conn.cursor()
    try:
        first_name = data.get('name', '')
        last_name = data.get('last_name', '')
        if not first_name or not last_name:
            return jsonify({"error": "First name and last name are required."}), 400
        
        last_name_part = (last_name + '   ')[:3]
        first_name_part = (first_name + '  ')[:2]

        part1 = last_name_part[0].upper() + last_name_part[1:3].lower()
        part2 = first_name_part[0].upper() + first_name_part[1:].lower()
        
        member_id = part1 + part2

        cursor.execute("SELECT COUNT(*) FROM members WHERE member_id = ?", member_id)
        count = cursor.fetchone()[0]
        if count > 0:
            return jsonify({"error": f"Generated Member ID '{member_id}' already exists. Please modify the name slightly to create a unique ID."}), 409

        cursor.execute("""
            INSERT INTO members (member_id, name, last_name, phone, birthday, gender, primary_member, secondary_member)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, 
        member_id, data.get('name'), data.get('last_name'), data.get('phone'),
        data.get('birthday'), data.get('gender'), True, False)

        mem_start_date = date.today()
        
        expiry_year = mem_start_date.year + 1
        expiry_month = mem_start_date.month
        _, last_day = calendar.monthrange(expiry_year, expiry_month)
        membership_expires = date(expiry_year, expiry_month, last_day)

        cursor.execute("""
            INSERT INTO family (member_id, address, city, state, zip_code, email, founding_family, mem_start_date, membership_expires, active_flag, renewal_email_sent)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        member_id, data.get('address'), data.get('city'), data.get('state'), data.get('zip_code'),
        data.get('email'), data.get('founding_family', False), mem_start_date, membership_expires, True, False)
        
        conn.commit()
        email_details = {
            "email_type": "welcome",
            "email": data.get('email'),
            "name": data.get('name'),
            "last_name": data.get('last_name')
        }
        queue_email_to_sqs(email_details)
        return jsonify({"message": "Record added successfully!", "member_id": member_id}), 201
    except pyodbc.Error as ex:
        conn.rollback()
        sqlstate = ex.args[0]
        logging.error(f"Error adding record: {ex} - ({sqlstate})")
        return jsonify({"error": f"Database error: {ex}"}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route('/api/update_record/<member_id>', methods=['PUT'])
def update_record(member_id):
    data = request.json
    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor()
    try:
        member_keys = ['name', 'last_name', 'phone', 'birthday', 'gender']
        member_clauses = [f"{key} = ?" for key in data if key in member_keys]
        member_params = [data[key] for key in data if key in member_keys]
        
        original_name = data.get('original_name')
        original_last_name = data.get('original_last_name')
        is_primary = data.get('is_primary', False)

        where_clause = " WHERE member_id = ?"
        params = member_params
        params.append(member_id)

        if is_primary:
            where_clause += " AND primary_member = 1"
        elif original_name and original_last_name:
            where_clause += " AND name = ? AND last_name = ?"
            params.append(original_name)
            params.append(original_last_name)

        if member_clauses:
            query_member = f"UPDATE members SET {', '.join(member_clauses)}{where_clause}"
            cursor.execute(query_member, tuple(params))

        if is_primary:
            family_keys = ['address', 'city', 'state', 'zip_code', 'email', 'founding_family', 'active_flag']
            family_clauses = [f"{key} = ?" for key in data if key in family_keys]
            family_params = [data[key] for key in data if key in family_keys]

            if 'mem_start_date' in data and data['mem_start_date']:
                mem_start_date_str = data['mem_start_date']
                mem_start_date = datetime.strptime(mem_start_date_str, '%Y-%m-%d').date()
                
                expiry_year = mem_start_date.year + 1
                expiry_month = mem_start_date.month
                _, last_day = calendar.monthrange(expiry_year, expiry_month)
                membership_expires = date(expiry_year, expiry_month, last_day)
                
                family_clauses.extend(['mem_start_date = ?', 'membership_expires = ?', 'renewal_email_sent = ?'])
                family_params.extend([mem_start_date, membership_expires, True])
            
            if family_clauses:
                family_params.append(member_id)
                query_family = f"UPDATE family SET {', '.join(family_clauses)} WHERE member_id = ?"
                cursor.execute(query_family, tuple(family_params))

        conn.commit()
        if is_primary and is_renewal:
            email_details = {
                "email_type": "renewal_thank_you",
                "email": data.get('email'),
                "name": data.get('name'),
                "last_name": data.get('last_name')
            }
            queue_email_to_sqs(email_details)

        return jsonify({"message": "Record updated successfully!"}), 200
    except pyodbc.Error as ex:
        conn.rollback()
        sqlstate = ex.args[0]
        logging.error(f"Error updating record {member_id}: {sqlstate} - {ex}")
        return jsonify({"error": f"Database error: {ex}"}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route('/api/delete_record/<member_id>', methods=['DELETE'])
def delete_record(member_id):
    data = request.json
    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500
    
    cursor = conn.cursor()
    try:
        if data and 'name' in data and 'last_name' in data:
            cursor.execute("DELETE FROM members WHERE member_id = ? AND name = ? AND last_name = ? AND primary_member = 0", 
                           member_id, data['name'], data['last_name'])
        else:
            cursor.execute("DELETE FROM members WHERE member_id = ?", member_id)
            cursor.execute("DELETE FROM family WHERE member_id = ?", member_id)
        
        conn.commit()
        if cursor.rowcount == 0:
            return jsonify({"error": "Record not found."}), 404
        return jsonify({"message": "Record deleted successfully!"}), 200
    except pyodbc.Error as ex:
        conn.rollback()
        sqlstate = ex.args[0]
        logging.error(f"Error deleting record {member_id}: {sqlstate} - {ex}")
        return jsonify({"error": f"Database error: {ex}"}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route('/api/add_secondary_member', methods=['POST'])
def add_secondary_member():
    data = request.json
    primary_member_id = data.get('primary_member_id')
    if not primary_member_id:
        return jsonify({"error": "Primary member ID is required."}), 400

    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500
    
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO members (member_id, name, last_name, phone, birthday, gender, primary_member, secondary_member)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, 
        primary_member_id, data.get('name'), data.get('last_name'),
        data.get('phone'), data.get('birthday'), data.get('gender'),
        False, True)
        
        conn.commit()
        return jsonify({"message": "Secondary member added successfully!"}), 201
    except pyodbc.Error as ex:
        conn.rollback()
        sqlstate = ex.args[0]
        logging.error(f"Error adding secondary member to family {primary_member_id}: {sqlstate} - {ex}")
        return jsonify({"error": f"Database error: {ex}"}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route('/api/visits/today/count', methods=['GET'])
def get_today_visit_count():
    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500

    try:
        cursor = conn.cursor()
        today_start = datetime.combine(date.today(), datetime.min.time())
        tomorrow_start = today_start + timedelta(days=1)
        sql_query = "SELECT COUNT(DISTINCT member_id) FROM Visits WHERE visit_datetime >= ? AND visit_datetime < ?"
        cursor.execute(sql_query, today_start, tomorrow_start)
        count = cursor.fetchone()[0]
        return jsonify({"count": count})
    except pyodbc.Error as ex:
        logging.error(f"Failed to count today's visits: {ex}")
        return jsonify({"error": "Could not retrieve visit count"}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/add_visit', methods=['POST'])
def add_visit():
    data = request.json
    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500
    
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO Visits (member_id, name, last_name, visit_datetime)
            VALUES (?, ?, ?, ?)
        """, data['member_id'], data['name'], data['last_name'], data['visit_datetime'])
        conn.commit()
        return jsonify({"message": "Visit recorded successfully!"}), 201
    except pyodbc.Error as ex:
        sqlstate = ex.args[0]
        logging.error(f"Error adding visit: {sqlstate} - {ex}")
        return jsonify({"error": f"Database error: {ex}"}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route('/api/visits/<member_id>/<name>/<last_name>', methods=['GET'])
def get_member_visits(member_id, name, last_name):
    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT visit_datetime FROM Visits
            WHERE member_id = ? AND name = ? AND last_name = ?
            ORDER BY visit_datetime DESC
        """, member_id, name, last_name)
        visits = [row[0].isoformat() for row in cursor.fetchall()]
        return jsonify(visits), 200
    except pyodbc.Error as ex:
        sqlstate = ex.args[0]
        logging.error(f"Error fetching visits for member {member_id}: {sqlstate} - {ex}")
        return jsonify({"error": f"Database error: {ex}"}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route('/api/visits/today', methods=['GET'])
def get_today_visits():
    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor()
    try:
        today_start = datetime.combine(date.today(), datetime.min.time())
        tomorrow_start = today_start + timedelta(days=1)

        sql_query = """
            SELECT name, last_name, visit_datetime
            FROM Visits
            WHERE visit_datetime >= ? AND visit_datetime < ?
            ORDER BY visit_datetime DESC
        """
        cursor.execute(sql_query, today_start, tomorrow_start)
        
        columns = [column[0] for column in cursor.description]
        visits = []
        for row in cursor.fetchall():
            visit_dict = dict(zip(columns, row))
            visit_dict['visit_datetime'] = visit_dict['visit_datetime'].isoformat()
            visits.append(visit_dict)
        
        return jsonify(visits), 200
    except pyodbc.Error as ex:
        logging.error(f"Failed to fetch today's visits list: {ex}")
        return jsonify({"error": "Could not retrieve today's visits list"}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
            
def send_renewal_email_ses(recipient_email, member_name, expiration_date):
    """
    Sends a formatted renewal email using AWS SES.
    """
    SENDER = "The Childrens Museum <nelcm98@gmail.com>"
    AWS_REGION = "us-east-1"
    SUBJECT = "Your Children's Museum Membership Is Expiring Soon!"

    BODY_HTML = f"""
    <html>
    <head></head>
    <body style="font-family: Arial, sans-serif; color: #333;">
      <h2>Time to Renew Your Membership!</h2>
      <p>Dear {member_name},</p>
      <p>
        Thank you for being a valued member of The Children's Museum! We hope you've enjoyed a year of fun, learning, and discovery.
      </p>
      <p>
        This is a friendly reminder that your family's membership is scheduled to expire on 
        <b>{expiration_date.strftime('%B %d, %Y')}</b>.
      </p>
      <p>
        Renewing is easy! Simply visit our front desk on your next visit to continue your adventure with us for another year.
      </p>
      <p>We look forward to seeing you again soon!</p>
      <br>
      <p>Sincerely,</p>
      <p><b>The Children's Museum Team</b></p>
    </body>
    </html>
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
    except ClientError as e:
        logging.error(f"Email failed to send to {recipient_email}: {e.response['Error']['Message']}")
        return False
    else:
        logging.info(f"Email sent successfully to {recipient_email}! Message ID: {response['MessageId']}")
        return True

@app.route('/api/send_renewal_emails', methods=['POST'])
def send_renewal_emails():
    conn = get_db_connection()
    if conn is None: return jsonify({"error": "Database connection failed"}), 500
    cursor = conn.cursor()
    
    sqs_queue_url = os.environ.get('SQS_QUEUE_URL')
    if not sqs_queue_url:
        return jsonify({"error": "SQS_QUEUE_URL environment variable not set."}), 500
        
    sqs = boto3.client('sqs')
    
    try:
        today = date.today()
        query = """
            SELECT f.member_id, f.email, m.name, m.last_name, f.membership_expires
            FROM family as f
            LEFT JOIN members as m ON f.member_id = m.member_id AND m.primary_member = 1
            WHERE 
                f.founding_family = 0 AND f.active_flag = 1
                AND MONTH(f.membership_expires) = ? AND YEAR(f.membership_expires) = ?
                AND f.renewal_email_sent = 0
        """
        cursor.execute(query, today.month, today.year)
        expiring_members = cursor.fetchall()

        if not expiring_members:
            return jsonify({"message": "No members found requiring a renewal email."}), 200

        messages_sent = 0
        for member in expiring_members:
            member_id, email, name, last_name, expires = member
            if not email:
                logging.warning(f"Cannot queue renewal email for {name} {last_name}: No email on record.")
                continue

            message_body = json.dumps({
                'member_id': member_id,
                'email': email,
                'name': name,
                'last_name': last_name,
                'expires': expires.isoformat()
            })
            
            sqs.send_message(
                QueueUrl=sqs_queue_url,
                MessageBody=message_body
            )
            messages_sent += 1
        
        message = f"Process started. Successfully queued {messages_sent} renewal emails for sending."
        return jsonify({"message": message, "queued_count": messages_sent}), 200
        
    except pyodbc.Error as ex:
        logging.error(f"Database error during queuing of renewal emails: {ex.args[0]} - {ex}")
        return jsonify({"error": f"Database error: {ex}"}), 500
    except ClientError as e:
        logging.error(f"SQS error during queuing of renewal emails: {e}")
        return jsonify({"error": f"SQS error: {e}"}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

if __name__ == '__main__':
    app.run(host = '0.0.0.0', port = 5000, debug=True)