# Dockerfile

# Start from the official AWS Lambda base image for Python 3.9
FROM public.ecr.aws/lambda/python:3.9

# Set the working directory
WORKDIR /var/task

# Install all system dependencies
RUN yum update -y && \
    curl https://packages.microsoft.com/config/rhel/7/prod.repo | tee /etc/yum.repos.d/mssql-release.repo && \
    ACCEPT_EULA=Y yum install -y msodbcsql18 unixODBC-devel krb5-libs

# Copy and install Python requirements directly into the working directory
COPY requirements.txt .
RUN pip install -r requirements.txt -t .

# Copy necessary libraries from the system paths into a local 'lib' directory
RUN mkdir lib && \
    cp /opt/microsoft/msodbcsql18/lib64/libmsodbcsql-18*.* ./lib/ && \
    cp /usr/lib64/libodbc.so.* ./lib/ && \
    cp /usr/lib64/libodbcinst.so.* ./lib/ && \
    cp /usr/lib64/libltdl.so.* ./lib/

# Copy your application code and config file
COPY app.py lambda.py ses_handler.py renewal_trigger.py email_sender.py odbcinst.ini ./

# Set environment variables to use our packaged libraries and config
ENV LD_LIBRARY_PATH=./lib
ENV ODBCSYSINI=.

# Set the command to run your handler
CMD [ "lambda.handler" ]