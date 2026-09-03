FROM python:3.14.7-alpine3.24

EXPOSE 443

WORKDIR /app

COPY requirements.txt /app/
COPY VERSION /app/VERSION
COPY *.py /app/
COPY static /app/static
COPY root.crt /root/.postgresql/root.crt
COPY mysoccerleague.com.chained.crt /app/mysoccerleague.com.chained.crt
COPY psyched-runner-378322-6ea04e89b69e.json /app/psyched-runner-378322-6ea04e89b69e.json

RUN apk upgrade --no-cache
RUN python3 -m pip install --upgrade "pip>=26.2" "msgpack>=1.2.1" "setuptools>=83.0.0"
RUN pip3 install -r requirements.txt

CMD ["python3", "newMain.py"]
