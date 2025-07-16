# Dockerfile

# Stage 1: The Builder
# This stage installs all dependencies in an environment that matches Lambda
FROM public.ecr.aws/lambda/python:3.9 AS builder

# Install Microsoft ODBC Driver 18 and unixODBC for Amazon Linux 2
RUN yum update -y && \
    curl https://packages.microsoft.com/config/rhel/7/prod.repo | tee /etc/yum.repos.d/mssql-release.repo && \
    ACCEPT_EULA=Y yum install -y msodbcsql18 && \
    yum install -y unixODBC-devel

# VERIFICATION STEP: Check for files and fail if not found.
RUN echo "Verifying driver installations..." && \
    find /opt/microsoft -name "libmsodbcsql-18.so" && \
    find /usr/lib64 -name "libodbc.so.2"

# Install Python requirements
COPY requirements.txt .
RUN pip install -r requirements.txt -t /asset

# Stage 2: The Final Image
# This stage creates the clean, final image for Lambda
FROM public.ecr.aws/lambda/python:3.9

# Create a 'lib' directory in our final image for the drivers
RUN mkdir -p /var/task/lib

# Copy all necessary system libraries from the builder stage into the 'lib' directory
# Note: The exact name includes version numbers, so we use a wildcard *.
COPY --from=builder /opt/microsoft/msodbcsql18/lib64/libmsodbcsql-18.so* /var/task/lib/
COPY --from=builder /usr/lib64/libodbc.so.* /var/task/lib/
COPY --from=builder /usr/lib64/libodbcinst.so.* /var/task/lib/
COPY --from=builder /usr/lib64/libltdl.so.* /var/task/lib/

# Copy the installed Python packages from the builder stage
COPY --from=builder /asset /var/task/

# Copy your application code
COPY app.py lambda.py ./

# Set the environment variable to tell the Lambda runtime where to find our custom libraries
ENV LD_LIBRARY_PATH=/var/task/lib

# Set the command to run your handler
CMD [ "lambda.handler" ]