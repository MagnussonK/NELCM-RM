#V1
import pyodbc
from flask import Flask, request, jsonify
from flask_cors import CORS
import json
from datetime import date, datetime, timedelta
import logging
import calendar
import os


import boto3
from botocore.exceptions import ClientError


def get_database_password():
    secret_name = "nelcm-db"
    region_name = "us-east-1"

    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region_name
    )

    try:
        get_secret_value_response = client.get_secret_value(
            SecretId=secret_name
        )
    except ClientError as e:
        raise e

    secret_string = get_secret_value_response['SecretString']

    # Parse the JSON string and return only the password
    secret_data = json.loads(secret_string)
    return secret_data['password']

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)
# This specifies that only your website can access the API
#CORS(app, resources={r"/api/*": {"origins": ["http://www.kedainsights.com", "http://localhost:8000", "https://main.d16dydmehoeryz.amplifyapp.com"]}})
CORS(app)

# --- Database Configuration ---
SQL_SERVER_INSTANCE = 'nelcm.cy1ogm8uwbvo.us-east-1.rds.amazonaws.com,1433'
DATABASE_NAME = 'nelcm'
#ODBC_DRIVER = '{ODBC Driver 18 for SQL Server}'
ODBC_DRIVER = '/var/task/lib/libmsodbcsql-18.4.so.1.1'
DATABASE_UID = 'nelcm'

# Name of the secret in AWS Secrets Manager
SECRET_NAME = "nelcm-db" # Change to your secret's name or ARN
REGION_NAME = "us-east-1"

def get_db_connection():
    """Establishes a connection to the SQL Server database."""
    try:
        # Call the function to get the password from Secrets Manager
        db_password = get_database_password()

        conn = pyodbc.connect(
            driver=ODBC_DRIVER,
            server=SQL_SERVER_INSTANCE,
            database=DATABASE_NAME,
            uid=DATABASE_UID,
            # Use the fetched password here
            pwd=db_password,
            Encrypt='yes',
            TrustServerCertificate='yes'
        )
        logging.info("Database connection established successfully.")
        return conn
    except pyodbc.Error as ex:
        logging.error(f"DATABASE CONNECTION FAILED: {ex}")
        return None
    
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
        # Use LEFT JOIN to get all members and their corresponding family info
        cursor.execute("SELECT * FROM members LEFT JOIN family ON members.member_id = family.member_id")
        # Handling potential duplicate column names (like member_id)
        columns = [column[0] for column in cursor.description]
        rows = []
        for row in cursor.fetchall():
            row_dict = {}
            for i, col in enumerate(columns):
                # If a column name is already in the dict, it's likely a duplicate from the join.
                # We can decide which one to keep, here we just overwrite, which is usually fine
                # if the joined keys are identical.
                row_dict[col] = row[i]
            rows.append(row_dict)
        return jsonify(rows)
    except pyodbc.Error as ex:
        sqlstate = ex.args[0]
        logging.error(f"Error fetching data: {sqlstate} - {ex}")
        return jsonify({"error": f"Database error: {ex}"}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

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
            "UPDATE Families SET membership_expiration = ? WHERE id = ?",
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
        # CORRECTED: Use EOMONTH and DATEADD to set the expiry to the end of the month, one year later.
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
        
        # Generate member_id based on the specified format: GreMa for Mary Green
        last_name_part = (last_name + '   ')[:3]
        first_name_part = (first_name + '  ')[:2]

        part1 = last_name_part[0].upper() + last_name_part[1:3].lower()
        part2 = first_name_part[0].upper() + first_name_part[1:].lower()
        
        member_id = part1 + part2

        # Check for uniqueness before attempting to insert
        cursor.execute("SELECT COUNT(*) FROM members WHERE member_id = ?", member_id)
        count = cursor.fetchone()[0]
        if count > 0:
            return jsonify({"error": f"Generated Member ID '{member_id}' already exists. Please modify the name slightly to create a unique ID."}), 409

        # Insert into members table
        cursor.execute("""
            INSERT INTO members (member_id, name, last_name, phone, birthday, gender, primary_member, secondary_member)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, 
        member_id, data.get('name'), data.get('last_name'), data.get('phone'),
        data.get('birthday'), data.get('gender'), True, False)

        # Insert into family table
        mem_start_date = date.today()
        
        # Calculate expiry date as end of the month, one year later
        expiry_year = mem_start_date.year + 1
        expiry_month = mem_start_date.month
        _, last_day = calendar.monthrange(expiry_year, expiry_month)
        membership_expires = date(expiry_year, expiry_month, last_day)

        cursor.execute("""
            INSERT INTO family (member_id, address, city, state, zip_code, email, founding_family, mem_start_date, membership_expires, active_flag)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        member_id, data.get('address'), data.get('city'), data.get('state'), data.get('zip_code'),
        data.get('email'), data.get('founding_family', False), mem_start_date, membership_expires, True)
        
        conn.commit()
        return jsonify({"message": "Record added successfully!", "member_id": member_id}), 201
    except pyodbc.Error as ex:
        conn.rollback()
        sqlstate = ex.args[0]
        logging.error(f"Error adding record: {sqlstate} - {ex}")
        return jsonify({"error": f"Database error: {ex}"}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route('/api/update_record/<member_id>', methods=['PUT'])
def update_record(member_id):
    """
    Updates an existing member record across both members and family tables.
    """
    data = request.json
    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor()
    try:
        # Update members table
        member_keys = ['name', 'last_name', 'phone', 'birthday', 'gender']
        member_clauses = [f"{key} = ?" for key in data if key in member_keys]
        member_params = [data[key] for key in data if key in member_keys]
        
        # Add original name and last_name to WHERE clause for secondary members
        original_name = data.get('original_name')
        original_last_name = data.get('original_last_name')
        is_primary = data.get('is_primary', False)

        where_clause = " WHERE member_id = ?"
        params = member_params
        params.append(member_id)
        
#        if not is_primary and original_name and original_last_name:
#            where_clause += " AND name = ? AND last_name = ?"
#            params.append(original_name)
#            params.append(original_last_name)

        if is_primary:
            # If updating a primary member, target them specifically.
            where_clause += " AND primary_member = 1"
        elif original_name and original_last_name:
            # This part correctly handles updating secondary members.
            where_clause += " AND name = ? AND last_name = ?"
            params.append(original_name)
            params.append(original_last_name)

        if member_clauses:
            query_member = f"UPDATE members SET {', '.join(member_clauses)}{where_clause}"
            cursor.execute(query_member, tuple(params))

        # Update family table (only for primary members)
        if is_primary:
            # If mem_start_date is being updated, recalculate membership_expires
            if 'mem_start_date' in data and data['mem_start_date']:
                mem_start_date_str = data['mem_start_date']
                mem_start_date = datetime.strptime(mem_start_date_str, '%Y-%m-%d').date()
                
                expiry_year = mem_start_date.year + 1
                expiry_month = mem_start_date.month
                _, last_day = calendar.monthrange(expiry_year, expiry_month)
                
                # Add/overwrite the membership_expires in the data dict
                data['membership_expires'] = date(expiry_year, expiry_month, last_day)

            family_keys = ['address', 'city', 'state', 'zip_code', 'email', 'founding_family', 'mem_start_date', 'membership_expires', 'active_flag']
            family_clauses = [f"{key} = ?" for key in data if key in family_keys]
            family_params = [data[key] for key in data if key in family_keys]

            if family_clauses:
                family_params.append(member_id)
                query_family = f"UPDATE family SET {', '.join(family_clauses)} WHERE member_id = ?"
                cursor.execute(query_family, tuple(family_params))

        conn.commit()

        if cursor.rowcount == 0:
            return jsonify({"message": "Record updated, but no rows were changed in the last operation."}), 200

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
    """
    Deletes a member record. If it's a primary member, deletes the whole family from both tables.
    """
    data = request.json
    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500
    
    cursor = conn.cursor()
    try:
        if data and 'name' in data and 'last_name' in data:
            # Delete a specific secondary member from the members table only
            cursor.execute("DELETE FROM members WHERE member_id = ? AND name = ? AND last_name = ? AND primary_member = 0", 
                           member_id, data['name'], data['last_name'])
        else:
            # Delete the entire family from both tables
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
    """
    Adds a new secondary member to an existing family.
    """
    data = request.json
    primary_member_id = data.get('primary_member_id')
    if not primary_member_id:
        return jsonify({"error": "Primary member ID is required."}), 400

    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500
    
    cursor = conn.cursor()
    try:
        # Only need to insert into members table for a secondary member
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
    """Counts the number of distinct member visits for today."""
    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500

    try:
        cursor = conn.cursor()

        # --- OPTIMIZATION ---
        # Define a date range for today to allow the database to use an index.
        # This is much faster than applying a CAST function to every row.
        today_start = datetime.combine(date.today(), datetime.min.time())
        tomorrow_start = today_start + timedelta(days=1)

        # The new query uses the date range.
        sql_query = "SELECT COUNT(DISTINCT member_id) FROM Visits WHERE visit_datetime >= ? AND visit_datetime < ?"
        
        cursor.execute(sql_query, today_start, tomorrow_start)
        # --- END OPTIMIZATION ---
        
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
    """
    Records a new visit for a member.
    """
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
    """
    Fetches all visits for a specific member, ordered by visit_datetime descending.
    """
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
        visits = [row[0].isoformat() for row in cursor.fetchall()] # Return ISO format strings
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
    """Fetches a list of all member visits for today."""
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
            # Ensure datetime is converted to a string for JSON
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
            
# --- NEW: Endpoint to send renewal emails ---
@app.route('/api/send_renewal_emails', methods=['POST'])
def send_renewal_emails():
    """
    Scans for members whose membership expires in the current month and sends a renewal email.
    This is intended to be run on the 1st of each month.
    """
    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor()
    try:
        today = date.today()
        
        # In a real-world cron job, you might want this check. For manual triggering, it's commented out.
        # if today.day != 1:
        #     return jsonify({"message": "Not the first day of the month. No action taken."}), 200

        # Find members whose membership expires this month and who haven't been sent an email yet for this cycle.
        query = """
            SELECT f.member_id, f.email, m.name, m.last_name, f.membership_expires
            FROM family as f
            LEFT JOIN members as m ON f.member_id = m.member_id AND m.primary_member = 1
            WHERE 
                f.founding_family = 0
                AND f.active_flag = 1
                AND MONTH(f.membership_expires) = ?
                AND YEAR(f.membership_expires) = ?
                AND f.renewal_email_sent_date IS NULL
        """
        cursor.execute(query, today.month, today.year)
        expiring_members = cursor.fetchall()

        if not expiring_members:
            logging.info("No members found requiring a renewal email this month.")
            return jsonify({"message": "No members found requiring a renewal email."}), 200

        sent_count = 0
        for member in expiring_members:
            member_id, email, name, last_name, expires = member
            if not email:
                logging.warning(f"Cannot send renewal email to {name} {last_name} (ID: {member_id}): No email on record.")
                continue
            
            # --- Simulate Email Sending ---
            # In a real application, you would integrate a service like AWS SES here.
            logging.info(f"SIMULATING RENEWAL EMAIL to: {email} for member {name} {last_name} (ID: {member_id}). Membership expires on {expires.strftime('%Y-%m-%d')}.")
            # -----------------------------

            # Update the database to mark the email as sent
            update_query = "UPDATE family SET renewal_email_sent_date = ? WHERE member_id = ?"
            cursor.execute(update_query, today, member_id)
            sent_count += 1
        
        conn.commit()
        
        message = f"Process complete. Successfully sent {sent_count} renewal emails."
        logging.info(message)
        return jsonify({"message": message, "sent_count": sent_count}), 200

    except pyodbc.Error as ex:
        conn.rollback()
        sqlstate = ex.args[0]
        # Check for 'Invalid column name' error (207 in SQL Server)
        if '207' in sqlstate: 
             logging.error(f"Database error in send_renewal_emails: {ex}. It seems the 'renewal_email_sent_date' column is missing from the 'family' table.")
             return jsonify({"error": "Database schema error: 'renewal_email_sent_date' column not found in 'family' table. Please run the required ALTER TABLE script."}), 500
        logging.error(f"Database error sending renewal emails: {sqlstate} - {ex}")
        return jsonify({"error": f"Database error: {ex}"}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


if __name__ == '__main__':
    app.run(host = '0.0.0.0', port = 5000, debug=True)