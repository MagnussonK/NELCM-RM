# Dockerfile

# Start from the official AWS Lambda base image for Python 3.9
FROM public.ecr.aws/lambda/python:3.9

# Set the working directory for the Lambda function
WORKDIR /var/task

# Create a 'lib' directory in our image for the custom drivers
RUN mkdir -p /var/task/lib

# Copy our pre-downloaded driver files from the local 'drivers' folder into the image's 'lib' directory
COPY drivers/* /var/task/lib/

# Copy and install Python requirements
COPY requirements.txt .
RUN pip install -r requirements.txt -t .

# Copy your application code and ODBC configuration file
COPY app.py lambda.py odbcinst.ini ./

# Set environment variables to point to our packaged libraries and config
ENV LD_LIBRARY_PATH=/var/task/lib
ENV ODBCSYSINI=/var/task
