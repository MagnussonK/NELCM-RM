# lambda.py
from serverless_wsgi import handle
from app import app

def handler(event, context):
    # We call the 'handle' function that was imported from the module
    return handle(app, event, context)