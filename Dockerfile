FROM python:3.13.9-slim-bookworm

EXPOSE 443

WORKDIR /app

COPY requirements.txt /app/
COPY VERSION /app/VERSION
COPY *.py /app/
COPY root.crt /root/.postgresql/root.crt
COPY mslChain.pem /app/mslChain.pem
COPY psyched-runner-378322-6ea04e89b69e.json /app/psyched-runner-378322-6ea04e89b69e.json


RUN pip3 install -r requirements.txt

ARG STORAGE_ACCOUNT_NAME
ENV STORAGE_ACCOUNT_NAME $STORAGE_ACCOUNT_NAME

ARG mslUsername
ENV mslUsername $mslUsername
ARG mslPassword
ENV mslPassword $mslPassword
ARG db_url
ENV db_url $db_url
ARG EMAIL_USER
ENV EMAIL_USER $EMAIL_USER
ARG EMAIL_TOKEN
ENV EMAIL_TOKEN $EMAIL_TOKEN
ARG STORAGE_SECRET
ENV STORAGE_SECRET $STORAGE_SECRET
ARG LOG_LEVEL
ENV LOG_LEVEL $LOG_LEVEL

ENTRYPOINT ["python3", "newMain.py"]

# docker run -p 443:443 --name refmentor refmentor:latest
