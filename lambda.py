# lambda.py (Temporary Debugging Version)
import json
import serverless_wsgi

def handler(event, context):
    # This will list all available functions/attributes in the module
    available_names = dir(serverless_wsgi)
    
    print(f"Available names in serverless_wsgi: {available_names}")
    
    return {
        'statusCode': 200,
        'body': json.dumps({
            'message': 'Debugging serverless_wsgi module.',
            'available_names': available_names
        })
    }