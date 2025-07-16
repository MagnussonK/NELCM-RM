# lambda.py
import serverless_wsgi
from app import app # Imports your Flask app instance

def handler(event, context):
    """This is the handler that the Serverless Framework will deploy."""
    return serverless_wsgi(app, event, context)