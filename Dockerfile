# Build a static binary, then ship it with the data directory on a minimal image.
FROM rust:1-alpine AS build
RUN apk add --no-cache musl-dev
WORKDIR /src
COPY Cargo.toml Cargo.lock ./
COPY src ./src
RUN cargo build --release --locked --bin deadlock-sim

FROM alpine:3
RUN adduser -D app
WORKDIR /app
COPY --from=build /src/target/release/deadlock-sim ./deadlock-sim
COPY data ./data
RUN chown -R app /app/data
USER app
ENV PORT=8080
EXPOSE 8080
CMD ["./deadlock-sim", "serve", "--host", "0.0.0.0"]
