FROM public.ecr.aws/lambda/python:3.12

WORKDIR /var/task

RUN pip install --no-cache-dir uv

COPY src/shared/ /build/shared/
COPY src/m01_collector/ /build/m01_collector/

RUN uv pip install --no-cache --system \
    /build/shared \
    /build/m01_collector

COPY src/m01_collector/value_betting_collector/ ./value_betting_collector/

CMD ["value_betting_collector.handler.handler"]
