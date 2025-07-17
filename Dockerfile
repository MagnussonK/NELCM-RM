# Dockerfile


# Stage 1: The Builder
FROM public.ecr.aws/lambda/python:3.9 AS builder

# Install the Microsoft ODBC Driver, command-line tools, and unixODBC
RUN yum update -y && \
    curl https://packages.microsoft.com/config/rhel/7/prod.repo | tee /etc/yum.repos.d/mssql-release.repo && \
    ACCEPT_EULA=Y yum install -y msodbcsql18 mssql-tools18 && \
    yum install -y unixODBC-devel

# --- DEBUGGING STEP: List the contents of relevant directories ---
RUN echo "--- Contents of /opt directory ---" && \
    ls -lR /opt && \
    echo "--- Contents of /usr/lib64 directory ---" && \
    ls -lR /usr/lib64