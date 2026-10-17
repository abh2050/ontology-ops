# Ontology Driven Operational AI

Supply chain delivery exception investigation on AWS.
*Turn connected operational evidence into a reviewable action.*

> Status: under construction (M1, data and ontology). No measured results exist yet.

## Business problem

Operations analysts investigate late deliveries by joining order, seller, customer, and product records by hand. This project tests whether an ontology assisted workflow reduces that effort and prevents costly errors while keeping authorization and independent approval intact.

The product creates value in three measurable ways. It groups late orders that share a seller into one case, so the team opens fewer investigations. It assembles evidence automatically, so each investigation takes less time. Its deterministic validation blocks wrong seller attribution and double counted orders, so the team makes fewer costly mistakes.

| Scenario | Monthly exceptions | Net monthly value | Payback on $64,000 build and integration |
|---|---|---|---|
| Conservative | 1,000 | About $1,950 | About 33 months |
| Base | 1,000 | About $6,900 | About 9 months |
| Strong | 5,000 | About $35,000 | About 2 months |

All values above are assumptions written before the build. The build measures task success, error rates, authorization behavior, latency, and actual cloud cost. A customer pilot must supply exception volume, analyst cost, and the cost of each wrong attribution.

The project recommends a pilot only when quality, security, and approval gates pass and the ontology workflow beats the deterministic SQL baseline by a meaningful margin. If the baseline delivers most of the value, the recommendation is to ship the baseline and skip the AI cost.

Full assumptions, calculations, decision gates, and measured results: [docs/business_case.md](docs/business_case.md)

## User decision

Whether to open an evidence supported **internal** investigation case. The user does not decide whether to blame a seller, issue a refund, or promise a delivery date. The application never contacts customers or changes commerce records.

## Measured findings

Not yet measured.

## Pilot recommendation

Pending evaluation (M5).

## Evidence and video

Pending (M6).

## Architecture

Pending verification of the deployed system (M6).

## Stack

React 19, TypeScript 5, Vite, Tailwind CSS 4, TanStack Query, Cytoscape.js. Python 3.12, FastAPI, Pydantic 2. PostgreSQL 16, SQLAlchemy 2, psycopg 3, Alembic. Amazon Bedrock (Converse), SQS, Cognito, ECS Fargate, ALB, RDS, S3, Secrets Manager, ECR, CloudWatch, AWS CDK v2.

## Reproduction

```bash
uv sync --locked
docker compose up -d postgres
uv run ops migrate
uv run ops data import --directory data/raw/olist   # you supply the Kaggle files
uv run ops data validate
uv run ops data pick-as-of
uv run ops scenario generate --seed 42 --scenario base-v1
uv run pytest
```

Data: [Brazilian E-Commerce Public Dataset by Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce), CC BY-NC-SA 4.0. Download it with your own Kaggle account into `data/raw/olist/`. The data is not redistributed here.

## Synthetic layer disclosure

Olist has no carrier identities or causes of delay. An authored, seeded scenario (fictional carriers and disruption events) demonstrates context traversal. Every synthetic row and UI element is labeled "Synthetic scenario".

## Limitations

Olist contains order level delivery timestamps only: no seller shipment tracking, carriers, causes of delay, inventory, contact history, or cancellation timestamps. Timestamps are dataset local without a timezone.

## Cloud resource status

Nothing deployed.
