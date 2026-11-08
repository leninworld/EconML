FROM python@sha256:dddbf9c143d4d3dff1c68e104645bac612823d33ef09571c71eff41faf07c194
LABEL purpose="econml686-m0-hosted-baseline"
COPY uv-wheel.json bootstrap_uv.py /bootstrap/
RUN python /bootstrap/bootstrap_uv.py
RUN apt-get update && apt-get install -y --no-install-recommends graphviz
RUN dpkg-query -W > /bootstrap/debian-versions.txt && python --version > /bootstrap/python-version.txt && uv --version > /bootstrap/uv-version.txt
RUN useradd --uid 1000 --create-home worker && mkdir /work && chown 1000:1000 /work
USER 1000:1000
WORKDIR /work
ENTRYPOINT ["/bin/sleep", "infinity"]
