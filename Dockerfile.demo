# Demo image. Same as Dockerfile, plus the SQLite baseline restored on every start.
# Build only from a checkout that has demo/refmentor.sqlite (that file is gitignored).
FROM python:3.14.7-alpine3.24

EXPOSE 443

WORKDIR /app

COPY requirements.txt /app/
COPY VERSION /app/VERSION
COPY *.py /app/
COPY fonts /app/fonts
COPY static /app/static
COPY docs /app/docs
COPY staging-root.crt /root/.postgresql/root.crt
COPY demo/refmentor.sqlite /app/demo/refmentor.sqlite

RUN apk upgrade --no-cache
RUN python3 -m pip install --upgrade "pip>=26.2" "msgpack>=1.2.1" "setuptools>=83.0.0"
RUN pip3 install -r requirements.txt

CMD ["python3", "newMain.py"]
