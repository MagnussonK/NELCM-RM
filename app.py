# V3 - Adjust Dates for birthday
# Tried to add Login
import pyodbc
from flask import Flask, request, jsonify
from flask_cors import CORS
import json
from datetime import date, datetime, timedelta
import logging
import calendar
import os
from decimal import Decimal
from functools import wraps

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

def queue_email_to_sqs(email_details):
    """Helper function to send a message to the SQS queue."""
    sqs_queue_url = os.environ.get('SQS_QUEUE_URL')
    if not sqs_queue_url:
        logging.error("SQS_QUEUE_URL environment variable not set. Cannot queue email.")
        return False
    
    if not email_details.get('email'):
        logging.warning(f"Cannot queue email for member {email_details.get('name')}: No email address provided.")
        return False

    try:
        sqs = boto3.client('sqs')
        sqs.send_message(
            QueueUrl=sqs_queue_url,
            MessageBody=json.dumps(email_details, default=str)
        )
        logging.info(f"Successfully queued '{email_details.get('email_type')}' email for {email_details.get('email')}")
        return True
    except ClientError as e:
        logging.error(f"SQS error while queuing email: {e}")
        return False

def current_claims():
    event = request.environ.get('serverless.event', {})  # serverless-wsgi
    return (event.get('requestContext', {})
                .get('authorizer', {})
                .get('jwt', {})
                .get('claims', {}))

def current_user():
    c = current_claims()
    groups = c.get("cognito:groups")
    return {
        "sub": c.get("sub"),
        "email": c.get("email"),
        "groups": groups if isinstance(groups, list) else (groups.split(",") if groups else [])
    }

def require_roles(*roles):
    def deco(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            user = current_user()
            if not set(roles).intersection(user["groups"]):
                return jsonify({"error": "forbidden"}), 403
            return fn(*args, **kwargs)
        return inner
    return deco


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
        today_str = date.today().strftime('%Y-%m-%d')
        cursor.execute("""
            UPDATE family
            SET active_flag = CASE
                WHEN membership_expires < ? AND founding_family = 0 THEN 0
                ELSE active_flag
            END
        """, today_str)
        conn.commit()
        
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

@app.route('/api/update_expired_memberships', methods=['PUT'])
# @require_roles("admin")
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

@app.route('/api/add_record', methods=['POST'])
# @require_roles("admin")
def add_record():
    """
    Create a NEW family with a PRIMARY member.

    Adjustments:
    - Frontend supplies a single 'birthday' (YYYY-MM-DD). We store only birth_month_day (MM-DD) and birth_year.
    - If birthday is missing/invalid, default birth_month_day to '01-01' to satisfy NOT NULL constraint; birth_year stays NULL.
    - Provide defaults for mem_start_date (today) and membership_expires (EOM 12 months later) unless founding_family=1.
    """
    data = request.json or {}

    first = (data.get('name') or '').strip()
    last  = (data.get('last_name') or '').strip()
    if not first or not last:
        return jsonify({"error": "First and last name are required."}), 400

    # Build base member_id like LllFf, then uniquify with -NN
    base_id = (last[:3].ljust(3))[:3].title() + (first[:2].ljust(2))[:2].title()
    member_id = base_id

    # -- Birthday normalization -> birth_month_day / birth_year
    birthday_iso = (data.get('birthday') or '').strip() or None
    birth_month_day = '01-01'   # NOT NULL column default
    birth_year = None
    if birthday_iso:
        try:
            y, m, d = map(int, birthday_iso.split('-'))
            if 1 <= m <= 12 and 1 <= d <= 31:
                birth_month_day = f"{m:02d}-{d:02d}"
                birth_year = y
        except Exception:
            # keep defaults
            pass

    # -- Gender normalization -> bit/NULL
    g = data.get('gender')
    if isinstance(g, str):
        s = g.strip().lower()
        if s in ('true','1','male','m'): g = 1
        elif s in ('false','0','female','f'): g = 0
        else: g = None
    elif isinstance(g, bool):
        g = 1 if g else 0
    elif g in (0,1):
        g = int(g)
    else:
        g = None

    # -- Family defaults
    from datetime import date
    import calendar as _cal

    def end_of_month(dt):
        _, last_day = _cal.monthrange(dt.year, dt.month)
        return dt.replace(day=last_day)

    founding_family = data.get('founding_family')
    if isinstance(founding_family, str):
        founding_family = 1 if founding_family.strip().lower() in ('true','1','yes') else 0
    elif isinstance(founding_family, bool):
        founding_family = 1 if founding_family else 0
    elif founding_family in (0,1):
        founding_family = int(founding_family)
    else:
        founding_family = 0

    mem_start_date = (data.get('mem_start_date') or date.today().isoformat())
    try:
        y, m, d = map(int, mem_start_date.split('-'))
        from datetime import date as _date
        mem_start_dt = _date(y, m, d)
    except Exception:
        mem_start_dt = date.today()
        mem_start_date = mem_start_dt.isoformat()

    if founding_family == 1:
        membership_expires = None
    else:
        # Add 12 months, then set to EOM
        new_year = mem_start_dt.year + (1 if mem_start_dt.month + 12 > 12 else 0)
        new_month = ((mem_start_dt.month + 12 - 1) % 12) + 1
        from datetime import date as _date
        tmp = _date(new_year, new_month, 1)
        membership_expires = end_of_month(tmp).isoformat()

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
            INSERT INTO members (member_id, name, last_name, phone, gender, primary_member, secondary_member, birth_month_day, birth_year)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, 
        member_id,
        data.get('name'),
        data.get('last_name'),
        data.get('phone'),
        g,  # your normalized gender
        True,
        False,
        birth_month_day,
        birth_year
        )

        today = date.today()
        if membership_expires and membership_expires[:7] == today.strftime("%Y-%m"):
            renewal_email_sent = 0
        else:
            renewal_email_sent = 1

        mem_start_date = date.today()
        expiry_year = mem_start_date.year + 1
        expiry_month = mem_start_date.month
        _, last_day = calendar.monthrange(expiry_year, expiry_month)
        membership_expires = date(expiry_year, expiry_month, last_day)

        cursor.execute("""
            INSERT INTO family (
                member_id, address, city, state, zip_code, email, founding_family,
                mem_start_date, membership_expires, active_flag, renewal_email_sent
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        member_id, data.get('address'), data.get('city'), data.get('state'), data.get('zip_code'),
        data.get('email'), founding_family, mem_start_date, membership_expires, True, renewal_email_sent
        )

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
# @require_roles("admin")
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
        is_renewal = 'mem_start_date' in data and data['mem_start_date']

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

            if is_renewal:
                mem_start_date_str = data['mem_start_date']
                mem_start_date = datetime.strptime(mem_start_date_str, '%Y-%m-%d').date()
                expiry_year = mem_start_date.year + 1
                expiry_month = mem_start_date.month
                _, last_day = calendar.monthrange(expiry_year, expiry_month)
                membership_expires = date(expiry_year, expiry_month, last_day)
                
                family_clauses.extend(['mem_start_date = ?', 'membership_expires = ?', 'renewal_email_sent = ?'])
                # --- BUG FIX: renewal_email_sent should be set to False on renewal ---
                family_params.extend([mem_start_date, membership_expires, False])
            
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

@app.route('/api/send_renewal_emails', methods=['POST'])
# @require_roles("admin")
def send_renewal_emails():
    conn = get_db_connection()
    if conn is None: return jsonify({"error": "Database connection failed"}), 500
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            UPDATE family
            SET active_flag = 0
            WHERE membership_expires < ? AND founding_family = 0
        """, date.today())
        conn.commit()
        
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
            # Convert row to dictionary to access by name
            member_dict = {
                'member_id': member[0],
                'email': member[1],
                'name': member[2],
                'last_name': member[3],
                'expires': member[4]
            }
            
            email_details = {
                'email_type': 'renewal_reminder',
                'member_id': member_dict['member_id'],
                'email': member_dict['email'],
                'name': member_dict['name'],
                'last_name': member_dict['last_name'],
                'expires': member_dict['expires'].isoformat() if member_dict['expires'] else None
            }
            
            if queue_email_to_sqs(email_details):
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

@app.route('/api/delete_record/<member_id>', methods=['DELETE'])
# @require_roles("admin")
def delete_record(member_id):
    data = request.json
    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500
    cursor = conn.cursor()
    try:
        rows_deleted = 0
        if data and 'name' in data and 'last_name' in data:
            cursor.execute(
                "DELETE FROM members WHERE member_id = ? AND name = ? AND last_name = ? AND primary_member = 0",
                member_id, data['name'], data['last_name']
            )
            rows_deleted = cursor.rowcount
        else:
            cursor.execute("DELETE FROM members WHERE member_id = ?", member_id)
            rows_deleted += cursor.rowcount
            cursor.execute("DELETE FROM family WHERE member_id = ?", member_id)
            rows_deleted += cursor.rowcount
        conn.commit()
        if rows_deleted == 0:
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
# @require_roles("admin")
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
        # Birthday normalization (force 01-01 default)
        birthday_iso = (data.get('birthday') or '').strip() or None
        birth_month_day = '01-01'
        birth_year = None
        if birthday_iso:
            try:
                y, m, d = map(int, birthday_iso.split('-'))
                if 1 <= m <= 12 and 1 <= d <= 31:
                    birth_month_day = f"{m:02d}-{d:02d}"
                    birth_year = y
            except Exception:
                pass

        cursor.execute("""
            INSERT INTO members (member_id, name, last_name, phone, gender, primary_member, secondary_member, birth_month_day, birth_year)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        primary_member_id,
        data.get('name'),
        data.get('last_name'),
        data.get('phone'),
        data.get('gender'),
        False,
        True,
        birth_month_day,
        birth_year
        )

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
# @require_roles("admin")
def get_today_visit_count():
    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500

    try:
        cursor = conn.cursor()
        today_start = datetime.combine(date.today(), datetime.min.time())
        tomorrow_start = today_start + timedelta(days=1)
        sql_query = "SELECT COUNT(*) FROM Visits WHERE visit_datetime >= ? AND visit_datetime < ?"
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
# @require_roles("admin")
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
  
@app.route('/api/visits/today/grouped', methods=['GET'])
def get_today_visits_grouped():
    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor()
    try:
        today_start = datetime.combine(date.today(), datetime.min.time())
        tomorrow_start = today_start + timedelta(days=1)

        # Group by family (member_id) and primary name/last_name (as stored on each visit)
        sql = """
            SELECT member_id,
                   name,
                   last_name,
                   COUNT(*) AS visitors,
                   MAX(visit_datetime) AS last_visit
            FROM Visits
            WHERE visit_datetime >= ? AND visit_datetime < ?
            GROUP BY member_id, name, last_name
            ORDER BY last_visit DESC
        """
        cursor.execute(sql, today_start, tomorrow_start)

        cols = [c[0] for c in cursor.description]
        rows = []
        for r in cursor.fetchall():
            row = dict(zip(cols, r))
            row['last_visit'] = row['last_visit'].isoformat() if row.get('last_visit') else None
            rows.append(row)

        return jsonify(rows), 200
    except pyodbc.Error as ex:
        logging.error(f"Failed to fetch grouped visits: {ex}")
        return jsonify({"error": "Could not retrieve grouped visits"}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
  
if __name__ == '__main__':
    app.run(host = '0.0.0.0', port = 5000, debug=True)