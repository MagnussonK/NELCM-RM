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

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
app = Flask(__name__)
app.json = CustomJSONProvider(app)
CORS(app)

SQL_SERVER_INSTANCE = 'nelcm.cy1ogm8uwbvo.us-east-1.rds.amazonaws.com,1433'
DATABASE_NAME = 'nelcm'
DATABASE_UID = 'nelcm'
ODBC_DRIVER = '/var/task/lib/libmsodbcsql-18.4.so.1.1'

def get_database_password():
    secret_name = "nelcm-db"
    region_name = "us-east-1"
    session = boto3.session.Session()
    client = session.client(service_name='secretsmanager', region_name=region_name)
    try:
        get_secret_value_response = client.get_secret_value(SecretId=secret_name)
    except ClientError as e:
        logging.error(f"Failed to retrieve secret '{secret_name}': {e}")
        return None
    secret_string = get_secret_value_response['SecretString']
    secret_data = json.loads(secret_string)
    return secret_data['password']

def get_db_connection():
    try:
        db_password = get_database_password()
        if db_password is None:
            logging.error("Database password could not be retrieved. Aborting connection.")
            return None
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

# ------------ MEMBER APIs ------------

@app.route('/api/data', methods=['GET'])
def get_data():
    """Fetch all members and family info, birthday formatted."""
    conn = get_db_connection()
    if conn is None: return jsonify({"error": "Database connection failed"}), 500
    cursor = conn.cursor()
    try:
        query = """
            SELECT m.member_id, m.name, m.last_name, m.phone,
                m.birth_month_day, m.birth_year, m.gender,
                m.primary_member, m.secondary_member,
                f.address, f.city, f.state, f.zip_code, f.email, f.founding_family,
                f.mem_start_date, f.membership_expires, f.active_flag, f.renewal_email_sent
            FROM members AS m
            JOIN family AS f ON m.member_id = f.member_id
        """
        cursor.execute(query)
        columns = [column[0] for column in cursor.description]
        rows = []
        for row in cursor.fetchall():
            row_dict = dict(zip(columns, row))
            # Birthday as MM/DD or MM/DD/YYYY
            if row_dict.get('birth_month_day'):
                if row_dict.get('birth_year'):
                    row_dict['birthday'] = f"{row_dict['birth_month_day'].replace('-', '/')}/{row_dict['birth_year']}"
                else:
                    row_dict['birthday'] = row_dict['birth_month_day'].replace('-', '/')
            else:
                row_dict['birthday'] = ''
            rows.append(row_dict)
        return jsonify(rows)
    finally:
        cursor.close()
        conn.close()

@app.route('/api/add_record', methods=['POST'])
def add_record():
    data = (request.json or {})
    first = (data.get('name') or '').strip()
    last  = (data.get('last_name') or '').strip()
    if not first or not last:
        return jsonify({"error": "First and last name are required."}), 400

    # ---- Make a unique member_id: LllFf, add -NN if collision ----
    base_id = (last[:3].ljust(3))[:3].title() + (first[:2].ljust(2))[:2].title()  # e.g., Bar + Ol => BarOl
    member_id = base_id

    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500
    cur = conn.cursor()

    try:
        # Ensure uniqueness
        suffix = 1
        while True:
            cur.execute("SELECT COUNT(*) FROM members WHERE member_id = ?", (member_id,))
            (cnt,) = cur.fetchone()
            if cnt == 0:
                break
            suffix += 1
            member_id = f"{base_id}-{suffix:02d}"

        # ---- Normalize birthday (either YYYY-MM-DD or split) ----
        birth_month_day = None
        birth_year = None

        bday_str = (data.get('birthday') or '').strip()
        if bday_str:
            try:
                y, m, d = map(int, bday_str.split('-'))
                if 1 <= m <= 12 and 1 <= d <= 31:
                    birth_month_day = f"{m:02d}-{d:02d}"
                    birth_year = y
            except Exception:
                pass

        if birth_month_day is None:
            bm, bd, by = data.get('birth_month'), data.get('birth_day'), data.get('birth_year')
            try:
                if bm is not None and bd is not None:
                    m, d = int(bm), int(bd)
                    if 1 <= m <= 12 and 1 <= d <= 31:
                        birth_month_day = f"{m:02d}-{d:02d}"
            except Exception:
                birth_month_day = None
            try:
                if by not in (None, "", "None"):
                    birth_year = int(by)
            except Exception:
                birth_year = None

        # ---- Build column list safely ----
        cols, vals = [], []

        def add(col, val):
            cols.append(col); vals.append(val)

        add('member_id', member_id)
        add('name', first)
        add('last_name', last)
        add('email', (data.get('email') or None))
        add('phone', (data.get('phone') or None))
        add('address', (data.get('address') or None))
        add('city', (data.get('city') or None))
        add('state', (data.get('state') or None))
        add('zip_code', (data.get('zip_code') or None))

        # gender expected as bit/bool; accept 'true'/'false' strings too
        g = data.get('gender')
        if isinstance(g, str):
            g = True if g.lower() == 'true' else (False if g.lower() == 'false' else None)
        add('gender', g)

        if birth_month_day is not None:
            add('birth_month_day', birth_month_day)
        if birth_year is not None:
            add('birth_year', birth_year)

        # family/primary defaults
        add('primary_member', True)
        add('secondary_member', False)
        add('founding_family', bool(data.get('founding_family', False)))
        add('active_flag', True)                     # new families start Active
        add('mem_start_date', data.get('mem_start_date') or None)  # you can leave NULL; UI has Update Membership

        # plaque fields (optional)
        add('plaque_flg', bool(data.get('plaque_flg', False)))
        add('plaque_message', (data.get('plaque_message') or None))

        placeholders = ", ".join("?" for _ in cols)
        sql = f"INSERT INTO members ({', '.join(cols)}) VALUES ({placeholders})"
        cur.execute(sql, tuple(vals))
        conn.commit()

        return jsonify({"message": "Record added successfully!", "member_id": member_id}), 200

    except Exception as e:
        conn.rollback()
        return jsonify({"error": f"Add failed: {e}"}), 500
    finally:
        cur.close()
        conn.close()



@app.route('/api/update_record/<member_id>', methods=['PUT'])
def update_record(member_id):
    """Update a single member row. Family-level fields only on the primary row."""
    data = request.json or {}

    # Collapse birthday inputs into birth_month_day / birth_year if provided
    if 'birth_month' in data and 'birth_day' in data:
        data['birth_month_day'] = f"{str(data['birth_month']).zfill(2)}-{str(data['birth_day']).zfill(2)}"

    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500
    cur = conn.cursor()

    try:
        is_primary = bool(data.get('is_primary', False))
        original_name = data.get('original_name')
        original_last_name = data.get('original_last_name')

        # -------- person-level (this exact row only) --------
        person_keys = ['name', 'last_name', 'phone', 'gender', 'birth_month_day', 'birth_year']
        person_set = [f"{k} = ?" for k in person_keys if k in data]
        person_params = [data[k] for k in person_keys if k in data]

        if person_set:
            if not original_name or not original_last_name:
                return jsonify({"error": "original_name and original_last_name are required for person updates."}), 400

            sql_person = f"""
                UPDATE members
                   SET {', '.join(person_set)}
                 WHERE member_id = ?
                   AND name = ?
                   AND last_name = ?
                   AND primary_member = ?
            """
            person_params += [member_id, original_name, original_last_name, 1 if is_primary else 0]
            cur.execute(sql_person, tuple(person_params))

            if cur.rowcount == 0:
                conn.rollback()
                return jsonify({"error": "Target member row not found with provided identifiers."}), 404
            if cur.rowcount > 1:
                conn.rollback()
                return jsonify({"error": "Multiple rows would be updated (person-level). Aborting."}), 409

        # -------- family-level (primary row only) --------
        # Only if editing primary; ignore if secondary
        if is_primary:
            family_keys = [
                'email', 'address', 'city', 'state', 'zip_code',
                'founding_family', 'mem_start_date', 'active_flag',
                'plaque_flg', 'plaque_message'
            ]
            family_set = [f"{k} = ?" for k in family_keys if k in data]
            family_params = [data[k] for k in family_keys if k in data]

            if family_set:
                sql_family = f"""
                    UPDATE members
                       SET {', '.join(family_set)}
                     WHERE member_id = ?
                       AND primary_member = 1
                """
                family_params += [member_id]
                cur.execute(sql_family, tuple(family_params))

                if cur.rowcount == 0:
                    conn.rollback()
                    return jsonify({"error": "Primary row not found for family-level update."}), 404
                if cur.rowcount > 1:
                    conn.rollback()
                    return jsonify({"error": "Multiple primary rows updated (data integrity issue)."}), 409

        conn.commit()
        return jsonify({"message": "Record updated successfully!"}), 200

    except Exception as e:
        conn.rollback()
        return jsonify({"error": f"Update failed: {e}"}), 500
    finally:
        cur.close()
        conn.close()



@app.route('/api/delete_record/<member_id>', methods=['DELETE'])
def delete_record(member_id):
    """
    Delete a SINGLE secondary member only.
    Primary members and whole-family deletions are not allowed.
    Body must include { "name": "...", "last_name": "..." }.
    """
    data = request.get_json(silent=True) or {}
    name = data.get('name')
    last_name = data.get('last_name')

    if not name or not last_name:
        # No name provided => someone tried to delete the whole family by member_id
        return jsonify({"error": "Family records cannot be deleted."}), 403

    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500
    cursor = conn.cursor()

    try:
        # Check if the target row is a primary member
        cursor.execute("""
            SELECT primary_member
            FROM members
            WHERE member_id = ? AND name = ? AND last_name = ?
        """, (member_id, name, last_name))
        row = cursor.fetchone()

        if not row:
            return jsonify({"error": "Member not found for provided identifiers."}), 404

        is_primary = bool(row[0])
        if is_primary:
            return jsonify({"error": "Primary members cannot be deleted."}), 403

        # Delete only this secondary row
        cursor.execute("""
            DELETE FROM members
            WHERE member_id = ? AND name = ? AND last_name = ? AND primary_member = 0
        """, (member_id, name, last_name))

        if cursor.rowcount != 1:
            # Should never delete more than one
            conn.rollback()
            return jsonify({"error": "Delete failed or would affect multiple rows. Aborted."}), 409

        conn.commit()
        return jsonify({"message": "Secondary member deleted successfully."}), 200

    except Exception as e:
        conn.rollback()
        return jsonify({"error": f"Delete failed: {e}"}), 500
    finally:
        cursor.close()
        conn.close()


@app.route('/api/add_secondary_member', methods=['POST'])
def add_secondary_member():
    """Add a secondary member with new birthday logic."""
    data = request.json
    primary_member_id = data.get('primary_member_id')
    if not primary_member_id:
        return jsonify({"error": "Primary member ID is required."}), 400
    conn = get_db_connection()
    if conn is None: return jsonify({"error": "Database connection failed"}), 500
    cursor = conn.cursor()
    try:
        birth_month = str(data.get('birth_month')).zfill(2)
        birth_day = str(data.get('birth_day')).zfill(2)
        birth_month_day = f"{birth_month}-{birth_day}"
        birth_year = data.get('birth_year') if data.get('birth_year') else None
        cursor.execute("""
            INSERT INTO members (member_id, name, last_name, phone, birth_month_day, birth_year, gender, primary_member, secondary_member)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        primary_member_id, data.get('name'), data.get('last_name'),
        data.get('phone'), birth_month_day, birth_year,
        data.get('gender'), False, True)
        conn.commit()
        return jsonify({"message": "Secondary member added successfully!"}), 201
    finally:
        cursor.close()
        conn.close()

# ------------ VISITS APIs ------------

@app.route('/api/add_visit', methods=['POST'])
def add_visit():
    """Record a visit."""
    data = request.json
    conn = get_db_connection()
    if conn is None: return jsonify({"error": "Database connection failed"}), 500
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO Visits (member_id, name, last_name, visit_datetime)
            VALUES (?, ?, ?, ?)
        """, data['member_id'], data['name'], data['last_name'], data['visit_datetime'])
        conn.commit()
        return jsonify({"message": "Visit recorded successfully!"}), 201
    finally:
        cursor.close()
        conn.close()

@app.route('/api/visits/<member_id>/<name>/<last_name>', methods=['GET'])
def get_member_visits(member_id, name, last_name):
    """Get all visits for a member."""
    conn = get_db_connection()
    if conn is None: return jsonify({"error": "Database connection failed"}), 500
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT visit_datetime FROM Visits
            WHERE member_id = ? AND name = ? AND last_name = ?
            ORDER BY visit_datetime DESC
        """, member_id, name, last_name)
        visits = [row[0].isoformat() for row in cursor.fetchall()]
        return jsonify(visits), 200
    finally:
        cursor.close()
        conn.close()

@app.route('/api/visits/today', methods=['GET'])
def get_today_visits():
    """Get today's visits."""
    conn = get_db_connection()
    if conn is None: return jsonify({"error": "Database connection failed"}), 500
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
    finally:
        cursor.close()
        conn.close()

@app.route('/api/visits/today/count', methods=['GET'])
def get_today_visit_count():
    """Count of today's unique visits."""
    conn = get_db_connection()
    if conn is None: return jsonify({"error": "Database connection failed"}), 500
    try:
        cursor = conn.cursor()
        today_start = datetime.combine(date.today(), datetime.min.time())
        tomorrow_start = today_start + timedelta(days=1)
        sql_query = "SELECT COUNT(DISTINCT member_id) FROM Visits WHERE visit_datetime >= ? AND visit_datetime < ?"
        cursor.execute(sql_query, today_start, tomorrow_start)
        count = cursor.fetchone()[0]
        return jsonify({"count": count})
    finally:
        cursor.close()
        conn.close()

# ------------ RENEWALS & MEMBERSHIP ------------

@app.route('/api/update_expired_memberships', methods=['PUT'])
def update_expired_memberships():
    """Deactivate expired memberships."""
    conn = get_db_connection()
    if conn is None: return jsonify({"error": "Database connection failed"}), 500
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
        return jsonify({"message": f"Expired memberships updated. {updated_rows} records affected."}), 200
    finally:
        cursor.close()
        conn.close()

@app.route('/api/send_renewal_emails', methods=['POST'])
def send_renewal_emails():
    """Queue renewal emails for expiring memberships."""
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
        messages_sent = 0
        for member in expiring_members:
            email_details = {
                'email_type': 'renewal_reminder',
                'member_id': member[0],
                'email': member[1],
                'name': member[2],
                'last_name': member[3],
                'expires': member[4].isoformat() if member[4] else None
            }
            if queue_email_to_sqs(email_details):
                messages_sent += 1
        return jsonify({"message": f"Process started. {messages_sent} renewal emails queued."}), 200
    finally:
        cursor.close()
        conn.close()

if __name__ == '__main__':
    app.run(host = '0.0.0.0', port = 5000, debug=True)
