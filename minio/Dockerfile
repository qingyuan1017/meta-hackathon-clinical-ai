FROM golang:1.24.8-alpine3.22 AS build

ARG MINIO_COMMIT=9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a

RUN apk add --no-cache git
RUN git init /src \
    && git -C /src remote add origin https://github.com/minio/minio.git \
    && git -C /src fetch --depth 1 origin "${MINIO_COMMIT}" \
    && git -C /src checkout --detach FETCH_HEAD \
    && test "$(git -C /src rev-parse HEAD)" = "${MINIO_COMMIT}"

WORKDIR /src
RUN CGO_ENABLED=0 GOOS=linux go build -tags kqueue -trimpath -o /out/minio

FROM alpine:3.22

RUN apk add --no-cache ca-certificates \
    && addgroup -S -g 10001 minio \
    && adduser -S -D -H -u 10001 -G minio minio \
    && mkdir -p /data \
    && chown -R minio:minio /data

COPY --from=build /out/minio /usr/local/bin/minio

USER 10001:10001
EXPOSE 9000 9001
VOLUME ["/data"]
ENTRYPOINT ["minio"]
CMD ["server", "/data", "--console-address", ":9001"]
