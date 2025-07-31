# renewal_trigger.py
import pyodbc
import json
from datetime import date
import logging
import os
import io

import boto3
from botocore.exceptions import ClientError

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
import smtplib
import ssl
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# --- Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# --- AWS Config ---
AWS_REGION = "us-east-1"
SES_SMTP_HOST = "email-smtp.us-east-1.amazonaws.com"
SES_SMTP_PORT = 465

def get_secret(secret_name):
    session = boto3.session.Session()
    client = session.client(service_name='secretsmanager', region_name=AWS_REGION)
    try:
        response = client.get_secret_value(SecretId=secret_name)
        return json.loads(response['SecretString'])
    except ClientError as e:
        logger.error(f"Failed to retrieve secret '{secret_name}': {e}")
        raise e

def get_db_connection():
    try:
        secrets = get_secret("nelcm-db")
        db_password = secrets.get('password')
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
    except Exception as e:
        logger.error(f"DATABASE CONNECTION FAILED: {e}")
        return None

def draw_letter_page(p, member_data):
    name = member_data.get('name', 'Valued')
    last_name = member_data.get('last_name', 'Member')
    address = member_data.get('address', '')
    city = member_data.get('city', '')
    state = member_data.get('state', '')
    zip_code = member_data.get('zip_code', '')
    expires_date = member_data.get('membership_expires')
    full_name = f"{name} {last_name}"
    city_state_zip = f"{city}, {state} {zip_code}".strip(', ')

    width, height = letter
    p.setFont("Helvetica", 10)
    p.drawString(0.5 * inch, height - 0.5 * inch, "The Children's Museum")
    p.drawString(0.5 * inch, height - 0.65 * inch, "323 Walnut St.")
    p.drawString(0.5 * inch, height - 0.8 * inch, "Monroe, LA 71201")

    p.setFont("Helvetica", 12)
    p.drawString(1 * inch, height - 2.5 * inch, full_name)
    p.drawString(1 * inch, height - 2.7 * inch, address)
    p.drawString(1 * inch, height - 2.9 * inch, city_state_zip)

    p.drawRightString(width - 0.75 * inch, height - 1.5 * inch, date.today().strftime("%B %d, %Y"))

    text = p.beginText(1 * inch, height - 4 * inch)
    text.setFont("Helvetica", 12)
    text.setLeading(14)
    text.textLine(f"Dear {full_name},")
    text.textLine("")
    text.textLine("Thank you for being a valued member of The Children's Museum!")
    text.textLine("")
    text.textLine("This is a friendly reminder that your family's membership is scheduled to expire on")
    if expires_date:
        text.textLine(f"{expires_date.strftime('%B %d, %Y')}.")
    else:
        text.textLine("the end of this month.")
    text.textLine("")
    text.textLine("Renewing is easy! Simply visit our front desk on your next visit.")
    text.textLine("")
    text.textLine("We look forward to seeing you again soon!")
    text.textLine("")
    text.setFont("Helvetica-Bold", 12)
    text.textLine("The Children's Museum Team")
    p.drawText(text)
    p.showPage()

def send_pdf_email(pdf_buffer, recipient):
    SENDER_EMAIL = "The Childrens Museum <nelcm98@gmail.com>"
    SUBJECT = f"Monthly Renewal Mailer PDF - {date.today().strftime('%B %Y')}"
    BODY_TEXT = "Attached is the generated PDF containing renewal letters for members expiring this month."

    try:
        secret_data = get_secret("nelcm-db")
        SMTP_USERNAME = secret_data['smtp_user']
        SMTP_PASSWORD = secret_data['smtp_password']
    except Exception as e:
        logger.error(f"Could not retrieve SMTP credentials for PDF mailer: {e}")
        return False

    msg = MIMEMultipart()
    msg['Subject'] = SUBJECT
    msg['From'] = SENDER_EMAIL
    msg['To'] = recipient
    msg.attach(MIMEText(BODY_TEXT, 'plain'))

    pdf_attachment = MIMEApplication(pdf_buffer.read(), _subtype="pdf")
    pdf_attachment.add_header('Content-Disposition', 'attachment', filename=f"renewal_mailer_{date.today().strftime('%Y_%m')}.pdf")
    msg.attach(pdf_attachment)

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(SES_SMTP_HOST, SES_SMTP_PORT, context=context) as server:
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(SENDER_EMAIL, recipient, msg.as_string())
            logger.info(f"Renewal mailer PDF successfully sent to {recipient}")
        return True
    except Exception as e:
        logger.error(f"SMTP failed to send PDF mailer to {recipient}: {e}")
        return False

def handler(event, context):
    logger.info("Starting monthly renewal process...")
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

        logger.info(f"Checking for memberships expiring in {current_month}/{current_year}...")

        # ✅ Pull all expiring families this month, regardless of renewal flag
        query = """
            SELECT f.member_id, f.email, m.name, m.last_name, f.membership_expires,
                   f.address, f.city, f.state, f.zip_code, f.renewal_email_sent
            FROM family as f
            JOIN members as m ON f.member_id = m.member_id AND m.primary_member = 1
            WHERE 
                f.founding_family = 0 AND f.active_flag = 1
                AND MONTH(f.membership_expires) = ? AND YEAR(f.membership_expires) = ?
        """
        cursor.execute(query, current_month, current_year)

        columns = [column[0] for column in cursor.description]
        expiring_members = [dict(zip(columns, row)) for row in cursor.fetchall()]

        if not expiring_members:
            logger.info("No members are expiring this month. Process complete.")
            return {'statusCode': 200, 'body': json.dumps({'message': 'No members expiring this month.'})}

        logger.info(f"Found {len(expiring_members)} members expiring this month.")

        # ✅ Generate PDF for all expiring families
        buffer = io.BytesIO()
        p = canvas.Canvas(buffer, pagesize=letter)
        for member in expiring_members:
            draw_letter_page(p, member)
        p.save()
        buffer.seek(0)

        send_pdf_email(buffer, "kris@kedainsights.com")

        # ✅ Only queue emails for members who haven't received one
        sqs_queue_url = os.environ.get('SQS_QUEUE_URL')
        if not sqs_queue_url:
            raise EnvironmentError("SQS_QUEUE_URL environment variable not set.")

        sqs = boto3.client('sqs')
        queued_count = 0
        for member in expiring_members:
            if member.get('email') and not member.get('renewal_email_sent'):
                email_details = {
                    'email_type': 'renewal_reminder',
                    'member_id': member['member_id'],
                    'email': member['email'],
                    'name': member['name'],
                    'last_name': member['last_name'],
                    'expires': member['membership_expires'].isoformat()
                }
                sqs.send_message(
                    QueueUrl=sqs_queue_url,
                    MessageBody=json.dumps(email_details)
                )
                queued_count += 1

        logger.info(f"Queued {queued_count} renewal emails.")

        return {
            'statusCode': 200,
            'body': json.dumps({'message': f"Mailer PDF sent. {queued_count} emails queued."})
        }

    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        return {'statusCode': 500, 'body': json.dumps({'error': str(e)})}
    finally:
        if cursor: cursor.close()
        if conn: conn.close()
