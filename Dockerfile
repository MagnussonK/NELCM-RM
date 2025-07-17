# Dockerfile

# Stage 1: The Builder - Use a full Ubuntu image for reliable installation
FROM ubuntu:22.04 AS builder

# Set frontend to noninteractive to avoid prompts during installation
ENV DEBIAN_FRONTEND=noninteractive

# Install Python 3.9 from the deadsnakes PPA
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


# Stage 2: The Final Image
FROM public.ecr.aws/lambda/python:3.9

# Copy the required system libraries directly from the standard paths in the builder stage
COPY --from=builder /opt/microsoft/msodbcsql18/lib64/libmsodbcsql-18.so.* /var/task/lib/
COPY --from=builder /usr/lib/x86_64-linux-gnu/libodbc.so.* /var/task/lib/
COPY --from=builder /usr/lib/x86_64-linux-gnu/libodbcinst.so.* /var/task/lib/
COPY --from=builder /usr/lib/x86_64-linux-gnu/libltdl.so.* /var/task/lib/

# Copy the installed Python packages from the builder stage
COPY --from=builder /asset/ /var/task/

# Copy your application code and config file
COPY app.py lambda.py odbcinst.ini ./

# Set environment variables to point to our packaged libraries and config
ENV LD_LIBRARY_PATH=/var/task/lib
ENV ODBCSYSINI=/var/task