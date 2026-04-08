FROM public.ecr.aws/lambda/python:3.12

WORKDIR /var/task

RUN pip install --no-cache-dir uv

COPY src/shared/ /build/shared/
COPY src/api/ /build/api/

RUN uv pip install --no-cache --system \
    /build/shared \
    /build/api

COPY src/api/value_betting_api/ ./value_betting_api/

CMD ["value_betting_api.main.mangum_handler"]
