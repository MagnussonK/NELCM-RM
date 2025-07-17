# Dockerfile

# Stage 1: The Builder
FROM public.ecr.aws/lambda/python:3.9 AS builder

# Install the Microsoft ODBC Driver and unixODBC
RUN yum update -y && \
    curl https://packages.microsoft.com/config/rhel/7/prod.repo | tee /etc/yum.repos.d/mssql-release.repo && \
    ACCEPT_EULA=Y yum install -y msodbcsql18 unixODBC-devel

# Install Python requirements
COPY requirements.txt .
RUN pip install -r requirements.txt -t /asset

# Create a libs folder and dynamically find/copy all dependencies
RUN mkdir /lib_dist && \
    MSODBC_PATH=$(find /opt/microsoft -name "libmsodbcsql-18.so.*") && \
    cp $MSODBC_PATH /lib_dist/ && \
    ldd $MSODBC_PATH | awk 'NF == 4 {print $3};' | xargs -I '{}' cp -L '{}' /lib_dist/

# Stage 2: The Final Image
FROM public.ecr.aws/lambda/python:3.9

# Copy the consolidated libraries from the builder stage
COPY --from=builder /lib_dist /var/task/lib/

# Copy the installed Python packages from the builder stage
COPY --from=builder /asset /var/task/

# Copy your application code and config file
COPY app.py lambda.py odbcinst.ini ./

# Set environment variables
ENV LD_LIBRARY_PATH=/var/task/lib
ENV ODBCSYSINI=/var/task

# Set the command to run your handler
CMD [ "lambda.handler" ]