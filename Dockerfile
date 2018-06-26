FROM ubuntu:16.04
RUN mkdir /crump
COPY . /crump
VOLUME /crump
RUN apt-get update && apt-get install -y jq curl zip python-pip sqlite && apt-get clean && rm -rf /var/lib/apt/lists/*
RUN pip install csvkit
WORKDIR /crump
