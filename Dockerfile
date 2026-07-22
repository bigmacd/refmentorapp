FROM python:3.13.13-alpine3.23

EXPOSE 443

WORKDIR /app

COPY requirements.txt /app/
COPY VERSION /app/VERSION
COPY *.py /app/
COPY static /app/static
COPY root.crt /root/.postgresql/root.crt
COPY mysoccerleague.com.chained.crt /app/mysoccerleague.com.chained.crt
COPY psyched-runner-378322-6ea04e89b69e.json /app/psyched-runner-378322-6ea04e89b69e.json


RUN pip3 install -r requirements.txt

ENTRYPOINT ["python3", "newMain.py"]
