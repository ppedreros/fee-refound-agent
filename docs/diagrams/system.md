# System: the production target on AWS

The demo runs on one machine with Docker Compose. This is where the same containers would run in
production: the same two images, the same two database roles, and the same rule that the agent
only ever reads.

```mermaid
flowchart LR
    luis(["Luis's browser"])

    subgraph edge["Edge"]
        cf["CloudFront<br/>HTTPS, caching"]
        s3[("S3<br/>the built frontend")]
    end

    subgraph vpc["VPC"]
        subgraph public["Public subnets"]
            alb["Application Load Balancer<br/>/api/* only"]
            nat["NAT gateway"]
        end
        subgraph private["Private subnets"]
            api["ECS Fargate service<br/>FastAPI + LangGraph<br/>checks run in-process"]
            boot["ECS one-off task<br/>bootstrap: migrations,<br/>roles, seed, policy"]
            rds[("RDS PostgreSQL, Multi-AZ<br/>roles: app_writer, agent_reader")]
        end
    end

    secrets["Secrets Manager<br/>model keys, database URLs,<br/>masking salt"]
    watch["CloudWatch<br/>JSON logs, metrics, alarms:<br/>/health, error rate, run latency"]
    jev["Jev API<br/>(TypeSafe)"]
    openai["OpenAI API<br/>Luna, Sol"]

    luis --> cf
    cf -->|"static files"| s3
    cf -->|"/api/*"| alb
    alb --> api
    api -->|"app_writer: runs, decisions,<br/>the refund"| rds
    api -->|"agent_reader: every read<br/>the graph makes"| rds
    boot -->|"owner, before each deploy"| rds
    secrets -.->|"task environment"| api
    secrets -.-> boot
    api -->|"stdout"| watch
    api --> nat
    nat --> jev
    nat --> openai

    classDef aws fill:#FFFFFF,stroke:#001D3D,color:#001D3D
    classDef data fill:#EFEEED,stroke:#5f5b56,color:#001D3D
    classDef outside fill:#FFFFFF,stroke:#DC634B,stroke-width:2px,color:#001D3D
    class cf,alb,nat,api,boot,secrets,watch aws
    class s3,rds data
    class jev,openai,luis outside
```

**Why this shape.**
- **One backend service.** A check is a few seconds of mostly waiting on the models, so it runs
  in-process (D-api-2) and streams its steps to the page over server-sent events through the
  ALB. A queue and workers would earn their place only with many staff checking at once.
- **Two roles in one database.** The ECS task gets both URLs: `agent_reader` for every read the
  graph makes, `app_writer` for runs, decisions and the refund. The owner credentials reach only
  the one-off bootstrap task.
- **Nothing public but CloudFront.** The ALB accepts traffic only from CloudFront, the tasks and
  the database live in private subnets, and the models are reached through the NAT gateway.
- **Secrets stay out of images.** Secrets Manager fills the task environment; the code reads
  environment variables only, as it does locally from `.env`.

## How the local stack maps to it

| Compose (`docker-compose.yml`) | AWS |
|---|---|
| `frontend`: nginx serves the build and proxies `/api` to the backend | CloudFront + S3, with `/api/*` routed to the ALB |
| `backend`: the FastAPI image on port 8000 | The ECS Fargate service behind the ALB |
| `migrate`: `python -m backend.bootstrap`, once per start | The ECS one-off task, once per deploy |
| `db`: Postgres 16 with a volume | RDS PostgreSQL, Multi-AZ, with the same two login roles |
| `.env` | Secrets Manager, injected as task environment variables |
| Logs on stdout (JSON lines) | CloudWatch Logs, with metrics and alarms on top |
| Calls from the backend container to Jev and OpenAI | The same calls, through the NAT gateway |

The demo deploy (Render, phase B in `SPEC-delivery.md`) is a smaller version of the same picture:
one web service per image and a managed Postgres.
