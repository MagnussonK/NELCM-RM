# Dockerfile

# Stage 1: The Builder - Installs all dependencies and discovers sub-dependencies
FROM public.ecr.aws/lambda/python:3.9 AS builder

# Install the Microsoft ODBC Driver and unixODBC
RUN yum update -y && \
    curl https://packages.microsoft.com/config/rhel/7/prod.repo | tee /etc/yum.repos.d/mssql-release.repo && \
    ACCEPT_EULA=Y yum install -y msodbcsql18 unixODBC-devel

# Install Python requirements into a target directory
COPY requirements.txt .
RUN pip install -r requirements.txt -t /asset

# Create a dedicated directory for all system libraries
RUN mkdir /lib_dist
# Copy the main driver into it
RUN cp /opt/microsoft/msodbcsql18/lib64/libmsodbcsql-18.so.0.1 /lib_dist
# Use 'ldd' to find all of the driver's dependencies and copy them into the same directory
RUN ldd /lib_dist/libmsodbcsql-18.so.0.1 | awk 'NF == 4 {print $3};' | xargs -I '{}' cp -L '{}' /lib_dist


# Stage 2: The Final Image - Assembles the lean, final image for Lambda
FROM public.ecr.aws/lambda/python:3.9

# Copy all system libraries (the driver and all its dependencies) from the builder stage
COPY --from=builder /lib_dist /var/task/lib/

# Copy the installed Python packages from the builder stage
COPY --from=builder /asset /var/task/

# Copy your application code and config file
COPY app.py lambda.py odbcinst.ini ./

# Set environment variables to tell the system where to find our custom libraries and config
ENV LD_LIBRARY_PATH=/var/task/lib
ENV ODBCSYSINI=/var/task

# Set the command to run your handler
CMD [ "lambda.handler" ]