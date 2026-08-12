FROM python:3

RUN apt-get update \
    && apt-get install tesseract-ocr -y \
    python3 \
    #python-setuptools \
    python3-pip \
    && apt-get clean \
    && apt-get autoremove


ADD . /home/App
WORKDIR /home/App
COPY requirements.txt ./
COPY . .

RUN pip install -r requirements.txt

VOLUME ["/data"]
EXPOSE 5080 5080
CMD ["python" ,"app.py"]