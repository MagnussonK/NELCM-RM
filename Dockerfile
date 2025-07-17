# Dockerfile

# Stage 1: The Builder - Use a full Ubuntu image for reliable installation
FROM ubuntu:22.04 AS builder

# Set frontend to noninteractive to avoid prompts during installation
ENV DEBIAN_FRONTEND=noninteractive

# Add the deadsnakes PPA to get Python 3.9 and install it
RUN apt-get update && \
    apt-get install -y software-properties-common && \
    add-apt-repository ppa:deadsnakes/ppa && \
    apt-get update && \
    apt-get install -y python3.9 python3.9-dev python3-pip

# Install the Microsoft ODBC Driver and unixODBC
RUN apt-get install -y curl gnupg libltdl7
RUN curl https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor > microsoft.gpg
RUN install -o root -g root -m 644 microsoft.gpg /etc/apt/trusted.gpg.d/
RUN sh -c 'echo "deb [arch=amd64] https://packages.microsoft.com/ubuntu/22.04/prod $(lsb_release -cs) main" > /etc/apt/sources.list.d/mssql-release.list'
RUN apt-get update
RUN ACCEPT_EULA=Y apt-get install -y msodbcsql18 unixodbc-dev

# Install Python requirements
COPY requirements.txt .
RUN pip3 install -r requirements.txt -t /asset

# Create a libs folder and dynamically find/copy all dependencies
RUN mkdir /lib_dist && \
    MSODBC_PATH=$(find /opt/microsoft -name "libmsodbcsql-18.so.*") && \
    cp $MSODBC_PATH /lib_dist/ && \
    ldd $MSODBC_PATH | awk 'NF == 4 {print $3};' | xargs -I '{}' cp -L '{}' /lib_dist/

# Stage 2: The Final Image
FROM public.ecr.aws/lambda/python:3.9

# Copy all system libraries from the builder stage
COPY --from=builder /lib_dist/ /var/task/lib/

# Copy the installed Python packages from the builder stage
COPY --from=builder /asset/ /var/task/

# Copy your application code and config file
COPY app.py lambda.py odbcinst.ini ./

# Set environment variables
ENV LD_LIBRARY_PATH=/var/task/lib
ENV ODBCSYSINI=/var/task