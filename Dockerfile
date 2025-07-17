# Dockerfile

# Stage 1: The Builder
FROM public.ecr.aws/lambda/python:3.9 AS builder

# Install every possible dependency for pyodbc and the MS driver
RUN yum update -y && \
    yum install -y gcc-c++ unixODBC-devel python3-devel krb5-devel && \
    curl https://packages.microsoft.com/config/rhel/7/prod.repo | tee /etc/yum.repos.d/mssql-release.repo && \
    ACCEPT_EULA=Y yum install -y msodbcsql18 mssql-tools18

# Install Python requirements
COPY requirements.txt .
RUN pip install -r requirements.txt -t /asset

# Create a dedicated directory for all system libraries
RUN mkdir /lib_dist
# Use ldd to find the main driver and ALL of its dependencies and copy them
RUN MSODBC_PATH=$(find /opt/microsoft -name "libmsodbcsql-18.so.*") && \
    cp -L $MSODBC_PATH /lib_dist/ && \
    ldd $MSODBC_PATH | awk 'NF == 4 {print $3};' | xargs -I '{}' cp -L '{}' /lib_dist/


# Stage 2: The Final Image
FROM public.ecr.aws/lambda/python:3.9

# Copy all system libraries from the builder stage
COPY --from=builder /lib_dist/ /var/task/lib/

# Copy the installed Python packages from the builder stage
COPY --from=builder /asset/ /var/task/

# Copy your application code and config file
COPY app.py lambda.py odbcinst.ini ./

# Set environment variables to point to our packaged libraries and config
ENV LD_LIBRARY_PATH=/var/task/lib
ENV ODBCSYSINI=/var/task

# Ensure all our custom libraries are executable
RUN chmod -R 755 /var/task/lib