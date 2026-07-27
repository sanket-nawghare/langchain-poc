# Docker Configuration

The root `compose.yaml` runs:

- Weaviate 1.36.0 using the existing local image and a named volume.
- HAPI FHIR 8.10.0 backed by PostgreSQL 16 and a named volume. A small local
  derivative image fixes Tomcat directory ownership and still runs as the
  upstream non-root user.

Pinned upstream images:

| Service | Image | Digest |
|---|---|---|
| Weaviate | `cr.weaviate.io/semitechnologies/weaviate:1.36.0` | `sha256:8542bbc210e2f13a769083e8aecc46cc11e2aee0e6e6d431b973fce7a756ab5c` |
| HAPI FHIR base | `hapiproject/hapi:v8.10.0-3-tomcat` | `sha256:4699f6bc38c08d4726963f7f831ad3c8964486cdb740af6986e6b0a83d4432c4` |
| PostgreSQL | `postgres:16` | `sha256:b6ccf02e9b47eac0d67b5eaa0ef56fd59163bffa5506f64e96ceb5053130ec86` |

All published ports bind to `127.0.0.1`. Weaviate anonymous access is enabled
only for local development and must not be reused as a production
configuration. Weaviate telemetry and HAPI browser CORS are disabled.

## Lifecycle

Use the root Makefile:

```bash
make infra-config
make infra-up
make infra-status
make infra-logs
make infra-down
```

`make infra-down` retains data. To explicitly delete the Weaviate and HAPI
PostgreSQL volumes:

```bash
make infra-reset CONFIRM=1
```

The application SQLite database is stored at
`data/clinical_workflow.db`. It is ignored by Git and persists independently
of Docker Compose. Reset it explicitly with:

```bash
make app-data-reset CONFIRM=1
```

## Endpoints and Overrides

Default host endpoints:

- HAPI FHIR: `http://localhost:8080/fhir`
- HAPI PostgreSQL: `127.0.0.1:5434`
- Weaviate HTTP: `http://localhost:8081`
- Weaviate gRPC: `localhost:50051`

Override published ports with `HAPI_FHIR_PORT`, `HAPI_DB_PORT`,
`WEAVIATE_HTTP_PORT`, or `WEAVIATE_GRPC_PORT`. The HAPI database password is a
documented local-only default; override `HAPI_DB_PASSWORD` when needed.

### pgAdmin

Register a server in pgAdmin with:

| Setting | Value |
|---|---|
| Host name/address | `127.0.0.1` |
| Port | `5434` |
| Maintenance database | `hapi` |
| Username | `hapi` |
| Password | `hapi-local-only` |

Use the corresponding values if `HAPI_DB_PORT`, `HAPI_DB_NAME`,
`HAPI_DB_USER`, or `HAPI_DB_PASSWORD` are overridden. The database port is
bound to loopback and is not exposed to other machines.

## Backend Readiness

`GET /health/live` reports only whether the API process is serving requests.
`GET /health/ready` probes SQLite, HAPI FHIR, and Weaviate and returns:

- HTTP 200 with `status: ready` when all dependencies are available.
- HTTP 503 with `status: not_ready` when any dependency is unavailable.

Probe failures return stable, non-sensitive details instead of raw connection
exceptions.

## Upstream References

- [HAPI FHIR Docker image](https://hub.docker.com/r/hapiproject/hapi)
- [HAPI FHIR PostgreSQL support](https://hapifhir.io/hapi-fhir/docs/server_jpa/database_support.html)
- [Weaviate Docker installation](https://docs.weaviate.io/deploy/installation-guides/docker-installation)
- [Weaviate health endpoints](https://docs.weaviate.io/deploy/configuration/status)
