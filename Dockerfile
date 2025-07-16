# Dockerfile

# Stage 1: The Builder - Installs all dependencies
FROM public.ecr.aws/lambda/python:3.9 as builder

# Install system-level dependencies for pyodbc using yum
RUN yum install -y gcc-c++ unixODBC-devel

# Install Python requirements into a target directory
COPY requirements.txt .
RUN pip install -r requirements.txt -t /asset


# Stage 2: The Final Image - Creates the lean, final image for Lambda
FROM public.ecr.aws/lambda/python:3.9

# Create a 'lib' directory in our final image
RUN mkdir -p /var/task/lib

# Copy the required system libraries from the builder stage into the 'lib' directory
COPY --from=builder /usr/lib64/libodbc.so.2 /var/task/lib/
COPY --from=builder /usr/lib64/libodbcinst.so.2 /var/task/lib/
COPY --from=builder /usr/lib64/libltdl.so.7 /var/task/lib/

# Copy the installed Python packages from the builder stage
COPY --from=builder /asset /var/task/

# Copy your application code
COPY app.py lambda.py ./

# Set the environment variable to tell the Lambda runtime where to find our custom libraries
ENV LD_LIBRARY_PATH=/var/task/lib

# Set the command to run your handler
CMD [ "lambda.handler" ]