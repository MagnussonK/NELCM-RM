# Dockerfile

# Stage 1: The Builder
FROM public.ecr.aws/lambda/python:3.9 AS builder

# Install the Microsoft ODBC Driver, command-line tools, and unixODBC
RUN yum update -y && \
    curl https://packages.microsoft.com/config/rhel/7/prod.repo | tee /etc/yum.repos.d/mssql-release.repo && \
    ACCEPT_EULA=Y yum install -y msodbcsql18 mssql-tools18 && \
    yum install -y unixODBC-devel

# Install Python requirements
COPY requirements.txt .
RUN pip install -r requirements.txt -t /asset

# Stage 2: The Final Image
FROM public.ecr.aws/lambda/python:3.9

# Create a 'lib' directory in our final image for the drivers
RUN mkdir -p /var/task/lib

# Copy all necessary system libraries from the builder stage using the verified paths
COPY --from=builder /opt/microsoft/msodbcsql18/lib64/libmsodbcsql-18.so.1.1 /var/task/lib/
COPY --from=builder /usr/lib64/libodbc.so.2.0.0 /var/task/lib/libodbc.so.2
COPY --from=builder /usr/lib64/libodbcinst.so.2.0.0 /var/task/lib/libodbcinst.so.2
COPY --from=builder /usr/lib64/libltdl.so.7.3.0 /var/task/lib/libltdl.so.7

# Copy the installed Python packages from the builder stage
COPY --from=builder /asset /var/task/

# Copy your application code and config file
COPY app.py lambda.py odbcinst.ini ./

# Set environment variables to point to our packaged libraries and config
ENV LD_LIBRARY_PATH=/var/task/lib
ENV ODBCSYSINI=/var/task

# Set the command to run your handler
CMD [ "lambda.handler" ]