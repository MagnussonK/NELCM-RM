# Dockerfile

# Stage 1: The Builder
# This stage installs all dependencies in an environment that matches Lambda
FROM public.ecr.aws/lambda/python:3.9 as builder

# Install system dependencies for pyodbc
RUN yum install -y gcc-c++ unixODBC-devel

# Install Python requirements
COPY requirements.txt .
RUN pip install -r requirements.txt -t /asset

# Stage 2: The Final Image
# This stage creates the clean, final image for Lambda
FROM public.ecr.aws/lambda/python:3.9

# Copy the installed Python packages from the builder stage
COPY --from=builder /asset /var/task/

# Copy your application code
COPY app.py lambda.py ./

# Set the command to run your handler
CMD [ "lambda.handler" ]