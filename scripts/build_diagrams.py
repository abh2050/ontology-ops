"""Build the AWS architecture diagram set as editable draw.io files and SVG exports.

Every diagram reflects what infra/stack.py deployed and what M4.5/M5 measured. Icons are
draw.io's native AWS4 library (mxgraph.aws4). Output: docs/diagrams/<name>.drawio and
<name>.svg (the SVG embeds the editable diagram).

  uv run python scripts/build_diagrams.py
"""

from __future__ import annotations

import html
import shutil
import subprocess
from pathlib import Path
from xml.sax.saxutils import quoteattr

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "diagrams"
DRAWIO = Path("/Applications/draw.io.app/Contents/MacOS/draw.io")

# AWS category colours (AWS Architecture Icons guide)
COMPUTE, NETWORK, DATABASE, APPINT = "#ED7100", "#8C4FFF", "#C925D1", "#E7157B"
ML, SECURITY, STORAGE, MGMT = "#01A88D", "#DD344C", "#7AA116", "#E7157B"
INK = "#232F3E"


class Diagram:
    def __init__(self, name: str, title: str, width: int, height: int):
        self.name, self.title, self.w, self.h = name, title, width, height
        self.cells: list[str] = []
        self.n = 0

    def _id(self) -> str:
        self.n += 1
        return f"c{self.n}"

    def _cell(self, value: str, style: str, x, y, w, h, vertex=True) -> str:
        cid = self._id()
        kind = 'vertex="1"' if vertex else 'edge="1"'
        self.cells.append(
            f'<mxCell id="{cid}" value={quoteattr(value)} style={quoteattr(style)} '
            f'{kind} parent="1"><mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" '
            f'as="geometry"/></mxCell>')
        return cid

    # ---- shapes ---------------------------------------------------------------------
    def icon(self, res: str, fill: str, label: str, x, y, size=56) -> str:
        style = (f"sketch=0;outlineConnect=0;fontColor={INK};gradientColor=none;"
                 f"fillColor={fill};strokeColor=#ffffff;dashed=0;verticalLabelPosition=bottom;"
                 "verticalAlign=top;align=center;html=1;fontSize=11;fontStyle=0;aspect=fixed;"
                 f"pointerEvents=1;shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.{res};")
        return self._cell(label, style, x, y, size, size)

    def shape(self, shape: str, fill: str, label: str, x, y, w=50, h=50) -> str:
        style = (f"sketch=0;outlineConnect=0;fontColor={INK};gradientColor=none;"
                 f"fillColor={fill};strokeColor=none;dashed=0;verticalLabelPosition=bottom;"
                 "verticalAlign=top;align=center;html=1;fontSize=11;aspect=fixed;"
                 f"pointerEvents=1;shape=mxgraph.aws4.{shape};")
        return self._cell(label, style, x, y, w, h)

    def group(self, kind: str, label: str, x, y, w, h) -> str:
        spec = {
            "cloud": ("group_aws_cloud_alt", INK, "none", INK, 0, ""),
            "region": ("group_region", "#00A4A6", "none", "#147EBA", 1, ""),
            "vpc": ("group_vpc2", "#8C4FFF", "none", "#8C4FFF", 0, ""),
            "public": ("group_security_group", "#7AA116", "#F2F6E8", "#248814", 0,
                       "grStroke=0;"),
            "private": ("group_security_group", "#00A4A6", "#E6F6F7", "#147EBA", 0,
                        "grStroke=0;"),
        }[kind]
        icon, stroke, fill, font, dashed, extra = spec
        style = (f"points=[];outlineConnect=0;gradientColor=none;html=1;whiteSpace=wrap;"
                 "fontSize=12;fontStyle=1;container=0;pointerEvents=0;collapsible=0;"
                 f"recursiveResize=0;shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.{icon};"
                 f"{extra}strokeColor={stroke};fillColor={fill};verticalAlign=top;align=left;"
                 f"spacingLeft=30;fontColor={font};dashed={dashed};")
        return self._cell(label, style, x, y, w, h)

    def box(self, label: str, x, y, w, h, stroke="#879196", fill="#FFFFFF", font=INK,
            dashed=0, size=11, align="left", valign="top", bold=0, rounded=1) -> str:
        style = (f"rounded={rounded};arcSize=6;whiteSpace=wrap;html=1;strokeColor={stroke};"
                 f"fillColor={fill};fontColor={font};dashed={dashed};fontSize={size};"
                 f"align={align};verticalAlign={valign};spacing=8;fontStyle={bold};")
        return self._cell(label, style, x, y, w, h)

    def text(self, label: str, x, y, w, h, size=11, color=INK, bold=0, align="left") -> str:
        style = (f"text;html=1;align={align};verticalAlign=top;whiteSpace=wrap;"
                 f"fontSize={size};fontColor={color};fontStyle={bold};")
        return self._cell(label, style, x, y, w, h)

    def edge(self, src: str, dst: str, label: str = "", color="#545B64", dashed=0,
             both=False, exit_="", entry="", width=1.5, points=None) -> str:
        cid = self._id()
        pts = ("<Array as=\"points\">" + "".join(f'<mxPoint x="{x}" y="{y}"/>'
                                                  for x, y in points) + "</Array>"
               if points else "")
        style = (f"edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;endArrow=block;endFill=1;"
                 f"strokeColor={color};strokeWidth={width};dashed={dashed};fontSize=10;"
                 f"labelBackgroundColor=#ffffff;fontColor={INK};"
                 + ("startArrow=block;startFill=1;" if both else "") + exit_ + entry)
        self.cells.append(
            f'<mxCell id="{cid}" value={quoteattr(label)} style={quoteattr(style)} edge="1" '
            f'parent="1" source="{src}" target="{dst}"><mxGeometry relative="1" '
            f'as="geometry">{pts}</mxGeometry></mxCell>')
        return cid

    def message(self, x1, x2, y, label, dashed=0, color="#232F3E") -> None:
        """A sequence-diagram message between two lifelines at height y."""
        cid = self._id()
        style = (f"html=1;endArrow=block;endFill=1;strokeColor={color};dashed={dashed};"
                 "fontSize=10;labelBackgroundColor=#ffffff;fontColor=#232F3E;align=center;"
                 "verticalAlign=bottom;")
        if x1 == x2:  # self call
            style = style.replace("endArrow=block", "edgeStyle=orthogonalEdgeStyle;"
                                  "rounded=0;endArrow=block")
            pts = (f'<Array as="points"><mxPoint x="{x1 + 40}" y="{y}"/>'
                   f'<mxPoint x="{x1 + 40}" y="{y + 18}"/></Array>')
            src, dst = (x1, y), (x1, y + 18)
        else:
            pts, src, dst = "", (x1, y), (x2, y)
        self.cells.append(
            f'<mxCell id="{cid}" value={quoteattr(label)} style={quoteattr(style)} edge="1" '
            f'parent="1"><mxGeometry relative="1" as="geometry">'
            f'<mxPoint x="{src[0]}" y="{src[1]}" as="sourcePoint"/>'
            f'<mxPoint x="{dst[0]}" y="{dst[1]}" as="targetPoint"/>{pts}</mxGeometry></mxCell>')

    def lifeline(self, label, x, top, bottom, res=None, fill=None, w=150) -> float:
        if res:
            self.icon(res, fill, "", x + w / 2 - 20, top - 50, size=40)
        self.box(f"<b>{label}</b>", x, top, w, 40, stroke="#232F3E", fill="#F7F8F8",
                 align="center", valign="middle", size=11)
        cx = x + w / 2
        cid = self._id()
        self.cells.append(
            f'<mxCell id="{cid}" value="" style="endArrow=none;dashed=1;html=1;'
            f'strokeColor=#879196;" edge="1" parent="1"><mxGeometry relative="1" '
            f'as="geometry"><mxPoint x="{cx}" y="{top + 40}" as="sourcePoint"/>'
            f'<mxPoint x="{cx}" y="{bottom}" as="targetPoint"/></mxGeometry></mxCell>')
        return cx

    def header(self, subtitle: str) -> None:
        self.text(f"<b>{html.escape(self.title)}</b>", 20, 12, self.w - 40, 30, size=20)
        self.text(subtitle, 20, 42, self.w - 40, 22, size=12, color="#545B64")

    def xml(self) -> str:
        body = "".join(self.cells)
        return (f'<mxfile host="build_diagrams.py"><diagram name={quoteattr(self.title)} '
                f'id="{self.name}"><mxGraphModel dx="{self.w}" dy="{self.h}" grid="0" '
                f'gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" '
                f'page="1" pageScale="1" pageWidth="{self.w}" pageHeight="{self.h}" '
                f'background="#FFFFFF" math="0" shadow="0"><root><mxCell id="0"/>'
                f'<mxCell id="1" parent="0"/>{body}</root></mxGraphModel></diagram></mxfile>')


def br(*lines: str) -> str:
    return "<br>".join(lines)


# ---------------------------------------------------------------------------------------
# 1. Deployment architecture
# ---------------------------------------------------------------------------------------
def deployment() -> Diagram:
    d = Diagram("aws-deployment", "AWS deployment architecture", 1780, 1110)
    d.header("Ontology-driven operational AI · as deployed with AWS CDK v2 (Python) in us-east-2 · "
             "one stack, 84 resources, all tagged project=ontology-ops")
    users = d.shape("users", INK, br("<b>Users</b>", "operator · reviewer · viewer",
                                     "browser (React SPA)"), 40, 330, 56, 56)
    d.group("cloud", "AWS Cloud", 160, 80, 1600, 1000)
    cdn = d.icon("cloudfront", NETWORK, br("<b>Amazon CloudFront</b>", "default *.cloudfront.net",
                                           "AWS-managed TLS cert", "caching off (TTL 0)"),
                 200, 330)
    d.group("region", "Region us-east-2 (Ohio)", 330, 110, 1415, 955)
    d.group("vpc", "VPC 10.0.0.0/16 · 2 AZs · no NAT gateway", 450, 150, 740, 720)
    igw = d.shape("internet_gateway", NETWORK, br("<b>Internet</b>", "<b>gateway</b>"),
                  425, 340, 50, 50)
    d.box("<b>Availability Zone A</b>", 480, 195, 345, 655, stroke="#147EBA", fill="none",
          font="#147EBA", dashed=1, align="center")
    d.box("<b>Availability Zone B</b>", 835, 195, 340, 655, stroke="#147EBA", fill="none",
          font="#147EBA", dashed=1, align="center")
    d.group("public", "Public subnet A · route 0.0.0.0/0 → IGW", 492, 225, 322, 360)
    d.group("public", "Public subnet B · route 0.0.0.0/0 → IGW", 847, 225, 316, 360)
    d.group("private", "Private isolated subnet A · local routes only", 492, 600, 322, 235)
    d.group("private", "Private isolated subnet B · local routes only", 847, 600, 316, 235)
    alb = d.icon("elastic_load_balancing", NETWORK,
                 br("<b>Application Load Balancer</b>", "HTTP:80 · spans both AZs",
                    "ingress: CloudFront prefix list only"), 802, 275)
    api = d.icon("fargate", COMPUTE, br("<b>ECS Fargate · API service</b>",
                                        "FastAPI + React UI · 1 task",
                                        "0.25 vCPU · 0.5 GiB · ARM64",
                                        "public IP for egress · api-sg"), 610, 455)
    worker = d.icon("fargate", COMPUTE, br("<b>ECS Fargate · worker service</b>",
                                           "outbox relay + consumer · 1 task",
                                           "0.5 vCPU · 1 GiB · ARM64",
                                           "no inbound · worker-sg"), 900, 455)
    oneoff = d.icon("ecs", COMPUTE, br("<b>One-off tasks</b>", "migrate · import · seed",
                                       "ecs run-task"), 1000, 250, size=48)
    rds = d.icon("rds", DATABASE, br("<b>Amazon RDS PostgreSQL 16</b>", "db.t4g.micro · single-AZ",
                                     "20 GiB gp3 · encrypted · force_ssl",
                                     "db-sg: 5432 from app SGs"),
                 625, 680)
    d.text(br("DB subnet group spans A and B.", "Single-AZ: no standby runs in B",
              "(Multi-AZ is the scale trigger)."), 870, 770, 270, 60, size=10, color="#147EBA")

    # regional managed services (outside the VPC)
    col1, col2 = 1240, 1500
    sqs = d.icon("sqs", APPINT, br("<b>Amazon SQS · jobs</b>", "standard · 180 s visibility",
                                   "4-day retention"), col1, 170)
    dlq = d.icon("sqs", APPINT, br("<b>SQS dead-letter queue</b>", "after 5 receives",
                                   "14-day retention"), col2, 170)
    bedrock = d.icon("bedrock", ML, br("<b>Amazon Bedrock</b>", "Converse API",
                                       "Nova Lite · Nova 2 Lite (global)"), col1, 330)
    cw = d.icon("cloudwatch_2", MGMT, br("<b>Amazon CloudWatch</b>", "logs (7 days) · alarms",
                                         "DLQ not empty · queue age"), col2, 330)
    sm = d.icon("secrets_manager", SECURITY, br("<b>AWS Secrets Manager</b>",
                                                "one secret per DB role", "+ demo-users"),
                col1, 490)
    s3 = d.icon("s3", STORAGE, br("<b>Amazon S3</b>", "versioned · SSE",
                                  "imports/ · exports/ · staging 7 d"), col2, 490)
    ecr = d.icon("ecr", COMPUTE, br("<b>Amazon ECR</b>", "ARM64 app image",
                                    "keep last 5"), col1, 650)
    iam = d.icon("identity_and_access_management", SECURITY,
                 br("<b>AWS IAM</b>", "one task role per duty", "least privilege"), col2, 650)
    cfn = d.icon("cloudformation", MGMT, br("<b>AWS CloudFormation</b>",
                                            "CDK v2 stack + CDKToolkit"), col1, 800)
    cognito = d.icon("cognito", SECURITY, br("<b>Amazon Cognito</b>", "user pool",
                                             "no self sign-up", "code + PKCE"), 360, 640)

    d.edge(users, cdn, "① HTTPS")
    d.edge(cdn, igw, "② HTTP:80")
    d.edge(igw, alb, "", exit_="exitX=0.5;exitY=0;", entry="entryX=0;entryY=0.5;")
    d.edge(alb, api, "③ :8000", entry="entryX=0.5;entryY=0;")
    d.edge(api, rds, "④ SQL · TLS 5432", color=DATABASE)
    d.edge(worker, rds, "outbox · leases · checkpoints", color=DATABASE,
           exit_="exitX=0.5;exitY=1;", entry="entryX=1;entryY=0.25;")
    d.edge(worker, sqs, "⑤ send · receive · delete", color=APPINT,
           exit_="exitX=0.5;exitY=0;", entry="entryX=0;entryY=0.5;",
           points=[(928, 178), (1205, 178), (1205, 198)])
    d.edge(sqs, dlq, "redrive after 5 receives", color=APPINT, dashed=1,
           exit_="exitX=1;exitY=0.5;", entry="entryX=0;entryY=0.5;")
    d.edge(worker, bedrock, "⑥ Converse · strict JSON", color=ML,
           exit_="exitX=1;exitY=0.5;", entry="entryX=0;entryY=0.5;",
           points=[(1180, 483), (1180, 358)])
    d.edge(users, cognito, "sign-in · PKCE", color=SECURITY, dashed=1,
           exit_="exitX=0.5;exitY=1;", entry="entryX=0;entryY=0.5;")
    d.edge(api, cognito, "JWKS (verify token)", color=SECURITY, dashed=1,
           exit_="exitX=0;exitY=0.5;", entry="entryX=1;entryY=0.5;")
    d.edge(dlq, cw, "alarm", color=MGMT, dashed=1, exit_="exitX=1;exitY=0.5;",
           entry="entryX=1;entryY=0.5;", points=[(1700, 198), (1700, 358)])

    d.box(br("<b>Numbered request path</b>",
             "① Browser → CloudFront over HTTPS (TLS terminates at the edge).",
             "② CloudFront → ALB over HTTP:80; ALB security group admits only the AWS-managed",
             "    prefix list com.amazonaws.global.cloudfront.origin-facing.",
             "③ ALB → API task :8000 (api-sg admits only alb-sg).",
             "④ API → RDS with sslmode=require; authorization predicate runs inside every query.",
             "⑤ Worker relays the transactional outbox to SQS and consumes jobs (≤ 2 concurrent).",
             "⑥ Worker calls Bedrock Converse; a deterministic validator checks every answer."),
          470, 900, 720, 150, size=10)
    d.box(br("<b>All tasks</b> pull the image from ECR, receive DB credentials from Secrets",
             "Manager at start, and ship logs to CloudWatch. Egress to AWS APIs uses task",
             "public IPs through the IGW (no NAT, no VPC endpoints: ~$0 fixed network cost).",
             "API role: S3 only. Worker role: SQS + 2 Bedrock models. No role can approve",
             "proposals except via the API's DB role."), 1240, 925, 500, 120, size=10,
          fill="#F7F8F8")
    _ = (oneoff, ecr, sm, s3, iam, cfn)
    return d


# ---------------------------------------------------------------------------------------
# 2. Network and security boundaries
# ---------------------------------------------------------------------------------------
def network() -> Diagram:
    d = Diagram("network-security", "Network and security boundaries", 1600, 930)
    d.header("Security groups, routes, and encryption in transit and at rest · every rule below "
             "is in infra/stack.py and verified by preflight / smoke tests")
    users = d.shape("users", INK, br("<b>Internet users</b>"), 40, 300, 50, 50)
    cdn = d.icon("cloudfront", NETWORK, br("<b>CloudFront</b>", "TLS 1.2+ · AWS cert",
                                           "HTTP→HTTPS redirect"), 190, 297)
    d.group("vpc", "VPC 10.0.0.0/16", 330, 90, 960, 640)
    d.group("public", "Public subnets (A, B) · 0.0.0.0/0 → IGW", 350, 130, 540, 580)
    d.group("private", "Private isolated subnets (A, B) · no internet route", 910, 130, 360,
            580)
    sg = dict(stroke="#DD3522", fill="none", font="#DD3522", size=10)
    d.box("<b>alb-sg</b>  in: tcp/80 from pl-cloudfront-origin-facing", 380, 180, 230, 190, **sg)
    alb = d.icon("elastic_load_balancing", NETWORK, br("<b>ALB</b>", "listener HTTP:80"),
                 467, 245)
    d.box("<b>api-sg</b>  in: tcp/8000 from alb-sg", 650, 180, 215, 190, **sg)
    api = d.icon("fargate", COMPUTE, br("<b>API task</b>", "uvicorn :8000"), 730, 245)
    d.box("<b>worker-sg</b>  in: none", 380, 420, 230, 180, **sg)
    worker = d.icon("fargate", COMPUTE, br("<b>Worker task</b>", "egress only"), 467, 480)
    d.box("<b>oneoff-task-sg</b>  in: none", 650, 420, 215, 180, **sg)
    oneoff = d.icon("ecs", COMPUTE, br("<b>One-off tasks</b>", "migrate/import/seed"), 735, 485,
                    size=48)
    d.box(br("<b>db-sg</b>  in: tcp/5432 from api-sg, worker-sg,", "oneoff-task-sg · out: none"),
          940, 300, 300, 200, **sg)
    rds = d.icon("rds", DATABASE, br("<b>RDS PostgreSQL 16</b>", "rds.force_ssl=1",
                                     "storage encrypted (KMS)"), 1062, 375)
    aws = d.box(br("<b>AWS public APIs</b>", "SQS · Bedrock · ECR · Secrets Manager",
                   "CloudWatch · S3 · Cognito (HTTPS 443)"), 1330, 450, 240, 90,
                fill="#F7F8F8", size=10)

    d.edge(users, cdn, "HTTPS 443")
    d.edge(cdn, alb, "HTTP 80 (origin)")
    d.edge(alb, api, "8000")
    d.edge(api, rds, "TLS 5432", color=DATABASE, exit_="exitX=1;exitY=0.5;",
           entry="entryX=0;entryY=0.25;")
    d.edge(worker, rds, "TLS 5432", color=DATABASE, exit_="exitX=0.5;exitY=1;",
           entry="entryX=0.25;entryY=1;", points=[(495, 640), (1076, 640)])
    d.edge(oneoff, rds, "TLS 5432", color=DATABASE, dashed=1, exit_="exitX=0.5;exitY=1;",
           entry="entryX=0.75;entryY=1;", points=[(759, 620), (1104, 620)])
    d.edge(worker, aws, "HTTPS 443 via public IP + IGW", color="#545B64", dashed=1,
           exit_="exitX=0;exitY=0.5;", entry="entryX=0.5;entryY=1;",
           points=[(395, 508), (395, 690), (1450, 690)])

    d.box(br("<b>Encryption and secrets</b>",
             "• Viewer↔CloudFront TLS; RDS connections sslmode=require with force_ssl.",
             "• RDS storage, SQS (SSE-SQS), S3 (SSE-S3) encrypted at rest.",
             "• DB passwords generated in Secrets Manager, injected as ECS secrets;",
             "  never in images, env files, logs (SQLAlchemy hide_parameters=True).",
             "• Browser keeps Cognito tokens in session memory only."),
          40, 760, 520, 130, size=10)
    d.box(br("<b>Accepted residual risk (demo, D-024)</b>",
             "CloudFront→ALB is HTTP inside AWS (no custom domain/cert). The prefix list",
             "admits any CloudFront distribution, so the API still verifies a Cognito",
             "access token and a provisioned user on every request."),
          580, 760, 480, 130, size=10, stroke="#DD3522")
    d.box(br("<b>Identity</b>",
             "Cognito: no self sign-up; users only via ops seed-users.",
             "API verifies RS256 signature, issuer, expiry, token_use=access, client_id.",
             "A valid token without a provisioned user grants no data."),
          1080, 760, 490, 130, size=10)
    return d


# ---------------------------------------------------------------------------------------
# 3. Authenticated read path (sequence)
# ---------------------------------------------------------------------------------------
def request_flow() -> Diagram:
    d = Diagram("request-flow", "Authenticated read path", 1500, 860)
    d.header("Cognito authorization code + PKCE, then a scoped read · measured p95 591 ms at 20 "
             "concurrent readers through CloudFront (deployed)")
    top, bottom = 140, 800
    xs = {}
    for i, (name, res, fill) in enumerate([
            ("Browser (React)", None, None), ("Cognito hosted UI", "cognito", SECURITY),
            ("CloudFront", "cloudfront", NETWORK), ("ALB", "elastic_load_balancing", NETWORK),
            ("API · FastAPI on Fargate", "fargate", COMPUTE),
            ("RDS PostgreSQL", "rds", DATABASE)]):
        xs[name] = d.lifeline(name, 40 + i * 240, top, bottom, res, fill, w=170)
    b, c, f, a, p, r = xs.values()
    y = 210
    steps = [
        (b, c, "1  GET /oauth2/authorize · code_challenge (S256) · state", 0),
        (c, b, "2  302 → /auth/callback?code&state (state checked)", 1),
        (b, c, "3  POST /oauth2/token · code + code_verifier", 0),
        (c, b, "4  access token (kept in session memory only)", 1),
        (b, f, "5  GET /api/queue · Authorization: Bearer … · HTTPS", 0),
        (f, a, "6  forward (Authorization + query; no caching) · HTTP:80", 0),
        (a, p, "7  :8000", 0),
        (p, p, "8  verify JWT: RS256 via cached JWKS · iss · exp · token_use · client_id", 0),
        (p, r, "9  load principal: users + seller_grants (role ≠ scope)", 0),
        (p, r, "10  scoped SQL: VISIBLE_ORDER predicate before joins/aggregates", 0),
        (p, b, "11  200 JSON · Cache-Control: private, no-store (hidden ⇒ identical 404)", 1),
    ]
    for x1, x2, label, dashed in steps:
        d.message(x1, x2, y, label, dashed=dashed)
        y += 52 if x1 != x2 else 66
    d.box(br("<b>Why this is safe</b>",
             "• Scope is re-read from PostgreSQL on every request; nothing is cached by role.",
             "• An order is visible only if every seller on it is granted to the caller.",
             "• Logs carry route template, status, latency only: never IDs or tokens."),
          40, 790 - 20, 640, 70, size=10, fill="#F7F8F8")
    return d


# ---------------------------------------------------------------------------------------
# 4. Async job, AI stages, and independent approval (sequence)
# ---------------------------------------------------------------------------------------
def job_flow() -> Diagram:
    d = Diagram("job-flow", "Async AI job and independent approval", 1760, 1210)
    d.header("Transactional outbox → SQS → bounded worker → two AI stages → deterministic "
             "validator → reviewer approval in one database transaction")
    top, bottom = 150, 1060
    lanes = [("Operator UI", None, None), ("API (Fargate)", "fargate", COMPUTE),
             ("RDS PostgreSQL", "rds", DATABASE), ("Worker (Fargate)", "fargate", COMPUTE),
             ("SQS jobs + DLQ", "sqs", APPINT), ("Amazon Bedrock", "bedrock", ML),
             ("Reviewer UI", None, None)]
    xs = [d.lifeline(n, 30 + i * 200, top, bottom, res, fill, w=160)
          for i, (n, res, fill) in enumerate(lanes)]
    op, api, db, wk, q, br_, rv = xs
    y = 215
    steps = [
        (op, api, "POST /api/jobs · Idempotency-Key", 0),
        (api, db, "1 tx: INSERT job + outbox", 0),
        (api, op, "202 {job_id}", 1),
        (wk, db, "relay: poll outbox every 2 s (SKIP LOCKED)", 0),
        (wk, q, "SendMessage {job_id, event_id}", 0),
        (wk, db, "mark outbox sent", 0),
        (q, wk, "ReceiveMessage (visibility 180 s)", 1),
        (wk, db, "claim 120 s lease · re-check scope", 0),
        (wk, db, "reserve model_call + admit (daily cap) · state=sent", 0),
        (wk, br_, "Converse · planner (≤2k in / 512 out)", 0),
        (wk, db, "checkpoint plan", 0),
        (wk, db, "authorized tools (server-authored SQL)", 0),
        (wk, br_, "Converse · analyst (≤4k in / 768 out)", 0),
        (wk, wk, "validator: IDs · numbers · causal language · eligibility", 0),
        (wk, db, "state=ready + result + evidence hash", 0),
        (wk, q, "DeleteMessage (only after durable terminal state)", 0),
        (op, api, "poll GET /api/jobs/{id} (ETag) · POST …/proposal", 0),
        (rv, api, "POST /api/proposals/{id}/decision (expected_revision)", 0),
        (api, db, "1 tx: lock proposal · advisory lock · re-check · INSERT case + audit", 0),
    ]
    for x1, x2, label, dashed in steps:
        d.message(x1, x2, y, label, dashed=dashed)
        y += 44 if x1 != x2 else 60
    d.box(br("<b>Failure handling (all drilled on the deployed stack)</b>",
             "• <b>Crash before ack</b> → SQS redelivers after 180 s → claim sees a terminal job →",
             "  ack without work → still exactly one case.",
             "• <b>Bedrock timeout</b> → job held <i>unknown</i>; never auto-retried "
             "(ops recover-job).",
             "• <b>5 known provider failures</b> → circuit breaker open 60 s; one half-open probe.",
             "• <b>Poison message</b> → DLQ after 5 receives → CloudWatch alarm; no blind redrive.",
             "• <b>Grant revoked mid-job</b> → job blocked (SCOPE_CHANGED)."),
          30, 1080, 820, 120, size=10, fill="#FDF3F4", stroke=SECURITY)
    d.box(br("<b>Cost controls</b>",
             "• 100 admitted calls/day (live) · separate eval budget (ceiling 1,500).",
             "• ≤ 2 concurrent jobs · ≤ 2 calls per job · SDK retries disabled.",
             "• Measured: $0.00035 (Nova Lite) / $0.00206 (Nova 2 Lite) per completed job."),
          870, 1080, 600, 120, size=10, fill="#F7F8F8")
    return d


# ---------------------------------------------------------------------------------------
# 5. IAM task roles and database roles
# ---------------------------------------------------------------------------------------
def roles() -> Diagram:
    d = Diagram("iam-and-db-roles", "IAM task roles and database roles", 1640, 900)
    d.header("Least privilege at two layers · IAM decides which AWS APIs a task may call; "
             "PostgreSQL grants decide which rows and columns it may touch (tested matrix)")
    d.text("<b>IAM (one role per duty)</b>", 30, 80, 400, 24, size=14)
    rows = [
        ("API task role", br("s3:GetObject imports/*", "s3:Get/PutObject exports/*",
                             "<i>no</i> Bedrock · <i>no</i> SQS"), STORAGE),
        ("Worker task role", br("sqs:Send/Receive/DeleteMessage (jobs queue)",
                                "bedrock:InvokeModel (2 configured models only)"), ML),
        ("Migration task role", br("no AWS API permissions", "(DB master creds via ECS secrets)"),
         "#879196"),
        ("Import task role", br("s3:GetObject imports/*"), STORAGE),
        ("Seed task role", br("cognito-idp:AdminCreateUser / SetUserPassword / GetUser",
                              "secretsmanager: demo-users read/write"), SECURITY),
        ("Task execution roles", br("ecr pull · logs:PutLogEvents",
                                    "secretsmanager:GetSecretValue (own DB secret)"), COMPUTE),
    ]
    y = 115
    for name, perms, color in rows:
        d.box(f"<b>{name}</b>", 30, y, 200, 72, stroke=color, fill="#FFFFFF", valign="middle",
              size=12)
        d.box(perms, 240, y, 480, 72, stroke=color, fill="#F7F8F8", valign="middle", size=10)
        y += 88
    d.icon("identity_and_access_management", SECURITY, "", 660, 74, size=36)

    d.text("<b>PostgreSQL roles (separate credentials per role)</b>", 780, 80, 600, 24, size=14)
    db_rows = [
        ("ops_admin", "migration / owner", "owns schema · runs Alembic · creates runtime roles"),
        ("ops_import", "import task",
         "INSERT source + quarantine · UPDATE(manifest) · read/write synthetic tables"),
        ("ops_api", "API service",
         "SELECT source/synthetic/app · INSERT jobs, outbox, proposals, cases, drafts, audit · "
         "UPDATE(state, revision, reviewed_by, review_reason) on proposals"),
        ("ops_worker", "worker service",
         "SELECT source/synthetic · UPDATE(lease, checkpoint, result…) on jobs · "
         "UPDATE(sent_at) on outbox · INSERT/UPDATE model_calls, usage_days · "
         "<b>cannot</b> insert cases or approve"),
    ]
    y = 115
    for role, who, grants in db_rows:
        d.box(f"<b>{role}</b><br><span style='color:#545B64'>{who}</span>", 780, y, 170, 100,
              stroke=DATABASE, valign="middle", size=12)
        d.box(grants, 960, y, 650, 100, stroke=DATABASE, fill="#FBF4FC", valign="middle",
              size=10)
        y += 115
    d.box(br("<b>Never granted to any runtime role</b>: UPDATE/DELETE on users or seller_grants · "
             "UPDATE/DELETE/TRUNCATE on audit_events · superuser, CREATEROLE, CREATEDB, "
             "BYPASSRLS.",
             "Verified against PostgreSQL by tests/integration/test_m4_security.py "
             "(23 tables × 5 operations × 3 roles + every column-level UPDATE grant)."),
          780, 580, 830, 80, size=10, stroke="#DD3522", fill="#FDF3F4")
    d.box(br("<b>Approval integrity</b> lives in the API role's single transaction: the "
             "reviewer must differ from the proposer and independently hold scope; stale "
             "revisions, duplicate approvals, and competing proposals return 409."),
          780, 680, 830, 70, size=10, fill="#F7F8F8")
    return d


# ---------------------------------------------------------------------------------------
# 6. Deployment pipeline
# ---------------------------------------------------------------------------------------
def pipeline() -> Diagram:
    d = Diagram("deployment-pipeline", "Build, deploy, verify, and tear down", 1760, 640)
    d.header("Infrastructure as code with AWS CDK v2 · immutable ARM64 image · one-off ECS tasks "
             "for data · gated by preflight and verified by smoke tests and drills")
    where = {"ci": (INK, "Developer laptop / GitHub Actions"),
             "cp": (MGMT, "AWS control plane (CloudFormation, ECR)"),
             "rt": (COMPUTE, "AWS runtime (ECS tasks, RDS, Cognito)")}
    steps = [
        ("Preflight", "account · region · SCP probes · Bedrock invoke · tags · cost table", "ci"),
        ("Tests + lint", "pytest with Postgres · ruff · Playwright (GitHub Actions)", "ci"),
        ("Docker build", "linux/arm64 · uv sync --locked", "ci"),
        ("cdk bootstrap", "CDKToolkit stack (once per account/region)", "cp"),
        ("cdk synth + diff", "84 resources · project tag on all", "cp"),
        ("cdk deploy", "services at desired count 0", "cp"),
        ("ECR push", "immutable release tag", "cp"),
        ("run-task migrate", "create DB roles · Alembic migrations", "rt"),
        ("run-task import", "S3 CSVs → validate → pick as_of → scenario", "rt"),
        ("run-task seed", "Cognito users + seller grants", "rt"),
        ("cdk deploy (release)", "API + worker to 1 task each", "cp"),
        ("Verify", "HTTPS smoke 18/18 · load p95 591 ms · 4 failure drills", "rt"),
        ("Teardown", "tagged inventory dry run → destroy (snapshot choice) → re-list", "cp"),
    ]
    ids = []
    for i, (title, sub, kind) in enumerate(steps):
        row, col = divmod(i, 7)
        x = 30 + (col if row == 0 else 6 - col) * 245
        y = 120 if row == 0 else 330
        color = where[kind][0]
        ids.append(d.box(f"<b>{i + 1}. {title}</b><br>{sub}", x, y, 215, 110, stroke=color,
                         fill="#FFFFFF", valign="middle", align="center", size=11))
    for a, b in zip(ids, ids[1:], strict=False):
        d.edge(a, b, "", color="#879196", width=2)
    y = 500
    for i, (color, label) in enumerate(where.values()):
        d.box(label, 30 + i * 420, y, 390, 40, stroke=color, fill="#FFFFFF", valign="middle",
              align="center", size=11, bold=1)
    d.text("Each paid step (deploy, release, model jobs, teardown) ran only after explicit "
           "owner approval with a cost estimate.", 30, 560, 1200, 24, size=11,
           color="#545B64")
    return d


# ---------------------------------------------------------------------------------------
# 7. Ontology and data model
# ---------------------------------------------------------------------------------------
def ontology() -> Diagram:
    d = Diagram("ontology", "Ontology operational-commerce-v1", 1500, 760)
    d.header("Typed, versioned objects and relationships over PostgreSQL · synthetic types are "
             "declared synthetic and labelled everywhere they appear")
    real = dict(stroke="#232F3E", fill="#FFFFFF", align="center", valign="middle", size=12)
    synth = dict(stroke="#E7157B", fill="#FDF0F6", align="center", valign="middle", size=12,
                 dashed=1)
    app = dict(stroke="#147EBA", fill="#EEF6FC", align="center", valign="middle", size=12)
    cust = d.box("<b>Customer</b><br>customer_id", 60, 170, 170, 70, **real)
    order = d.box("<b>Order</b><br>order_id · timestamps<br>(masked at as_of)", 380, 160, 200,
                  90, **real)
    line = d.box("<b>OrderLine</b><br>order_id + line_no<br>price · freight (centavos)", 760,
                 160, 210, 90, **real)
    prod = d.box("<b>Product</b><br>product_id · category", 1130, 120, 190, 70, **real)
    seller = d.box("<b>Seller</b><br>seller_id · state", 1130, 260, 190, 70, **real)
    carrier = d.box("<b>Carrier</b> (synthetic)<br>scenario_id + carrier_code", 380, 380, 200,
                    80, **synth)
    event = d.box("<b>DisruptionEvent</b> (synthetic)<br>scenario_id + event_id", 60, 380, 230,
                  80, **synth)
    prop = d.box("<b>ActionProposal</b><br>proposal_id · revision · hashes", 760, 420, 230, 80,
                 **app)
    case = d.box("<b>InvestigationCase</b><br>case_id · case_key", 1130, 420, 200, 80, **app)
    d.edge(cust, order, "places · 1:N")
    d.edge(order, line, "contains · 1:N")
    d.edge(line, prod, "references · N:1")
    d.edge(line, seller, "fulfilled_by · N:1 (not blame)")
    d.edge(order, carrier, "shipped_by · N:1", color="#E7157B", dashed=1)
    d.edge(event, order, "overlaps · derived", color="#E7157B", dashed=1,
           exit_="exitX=1;exitY=0.25;", entry="entryX=0.15;entryY=1;")
    d.edge(prop, case, "approved by an independent reviewer", color="#147EBA")
    d.box(br("<b>Named derived functions</b> (a change needs a new ontology version)",
             "late_open_order(as_of) · known_delivery_state(as_of) · "
             "seller_associated_late_orders(as_of)",
             "eligible_investigation(scope, as_of) · event_overlap(order, event, as_of)"),
          60, 560, 700, 80, size=10, fill="#F7F8F8")
    d.box(br("<b>Display projection</b>: OrderLine collapses into an Order→Seller edge carrying "
             "line_no, product, price. Depth 2 = Order → Seller → related Order. ≤ 50 nodes; "
             "exact totals computed separately."),
          790, 560, 640, 80, size=10, fill="#F7F8F8")
    return d


def export(diagram: Diagram) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    src = OUT / f"{diagram.name}.drawio"
    src.write_text(diagram.xml())
    if not DRAWIO.exists():
        raise SystemExit("draw.io Desktop is required to export SVG")
    cli = shutil.which("drawio") or str(DRAWIO)
    subprocess.run([cli, "--disable-gpu", "--disable-update", "-x", "-f", "svg", "-e",
                    "--embed-svg-images", "-o", str(OUT / f"{diagram.name}.svg"), str(src)],
                   check=True, capture_output=True)
    print(f"wrote {src.relative_to(ROOT)} and .svg")


def main() -> None:
    for build in (deployment, network, request_flow, job_flow, roles, pipeline, ontology):
        export(build())


if __name__ == "__main__":
    main()
