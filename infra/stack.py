"""One CDK stack (spec 15). Deployed to us-east-2 because of the account SCP (D-023);
Bedrock calls go to us-east-1.

VPC (2 public + 2 private isolated subnets, no NAT), ALB with ACM HTTPS, ECS Fargate
API and worker services (public subnets with public IPs for outbound HTTPS), private
RDS PostgreSQL 16, SQS with DLQ, Cognito user pool and PKCE client, ECR, Secrets
Manager, S3, and CloudWatch logs and alarms. No account numbers or ARNs are written
in this file; they resolve at synth/deploy time.
"""

from __future__ import annotations

import hashlib

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
)
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_cloudwatch as cw
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk import aws_rds as rds
from aws_cdk import aws_route53 as r53
from aws_cdk import aws_route53_targets as r53_targets
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_secretsmanager as sm
from aws_cdk import aws_sqs as sqs
from constructs import Construct


def foundation_model_id(model_id: str) -> str:
    """Strip a cross-region inference profile prefix (global., us., eu., apac.)."""
    head, _, rest = model_id.partition(".")
    return rest if head in {"global", "us", "eu", "apac"} else model_id


class OntologyOpsStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, cfg: dict, models: dict,
                 domain: str, certificate_arn: str, image_tag: str, services_running: bool,
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        project = cfg["project_tag"]
        sizing = cfg["sizing"]
        retention = logs.RetentionDays.ONE_WEEK

        # ---- network ------------------------------------------------------------------
        vpc = ec2.Vpc(self, "Vpc", max_azs=2, nat_gateways=0, subnet_configuration=[
            ec2.SubnetConfiguration(name="public", subnet_type=ec2.SubnetType.PUBLIC,
                                    cidr_mask=24),
            ec2.SubnetConfiguration(name="private", subnet_type=ec2.SubnetType.PRIVATE_ISOLATED,
                                    cidr_mask=24),
        ])
        alb_sg = ec2.SecurityGroup(self, "AlbSg", vpc=vpc, description="ALB ingress")
        alb_sg.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(443), "HTTPS")
        alb_sg.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(80), "HTTP redirect")
        api_sg = ec2.SecurityGroup(self, "ApiSg", vpc=vpc, description="API tasks")
        api_sg.add_ingress_rule(alb_sg, ec2.Port.tcp(8000), "from ALB only")
        worker_sg = ec2.SecurityGroup(self, "WorkerSg", vpc=vpc,
                                      description="worker tasks: no inbound")
        task_sg = ec2.SecurityGroup(self, "OneOffTaskSg", vpc=vpc,
                                    description="one-off migration, import, seeding tasks")
        db_sg = ec2.SecurityGroup(self, "DbSg", vpc=vpc, description="RDS",
                                  allow_all_outbound=False)
        for sg, why in ((api_sg, "API"), (worker_sg, "worker"), (task_sg, "one-off tasks")):
            db_sg.add_ingress_rule(sg, ec2.Port.tcp(5432), f"PostgreSQL from {why}")

        # ---- secrets and database --------------------------------------------------------
        def role_secret(name: str, username: str) -> sm.Secret:
            return sm.Secret(self, f"{name}Secret", secret_name=f"{project}/db/{username}",
                             generate_secret_string=sm.SecretStringGenerator(
                                 secret_string_template=f'{{"username": "{username}"}}',
                                 generate_string_key="password", exclude_punctuation=True,
                                 password_length=32),
                             removal_policy=RemovalPolicy.DESTROY)

        import_secret = role_secret("Import", "ops_import")
        api_secret = role_secret("Api", "ops_api")
        worker_secret = role_secret("Worker", "ops_worker")
        demo_users_secret = sm.Secret(self, "DemoUsersSecret",
                                      secret_name=f"{project}/demo-users",
                                      description="Written by ops seed-users --mode aws",
                                      removal_policy=RemovalPolicy.DESTROY)

        params = rds.ParameterGroup(self, "DbParams",
                                    engine=rds.DatabaseInstanceEngine.postgres(
                                        version=rds.PostgresEngineVersion.VER_16),
                                    parameters={"rds.force_ssl": "1"})
        db = rds.DatabaseInstance(
            self, "Db",
            engine=rds.DatabaseInstanceEngine.postgres(version=rds.PostgresEngineVersion.VER_16),
            instance_type=ec2.InstanceType(sizing["rds"]["instance"]),
            vpc=vpc, vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED),
            security_groups=[db_sg], publicly_accessible=False, multi_az=False,
            allocated_storage=sizing["rds"]["storage_gib"], storage_type=rds.StorageType.GP3,
            storage_encrypted=True, database_name="ops", parameter_group=params,
            credentials=rds.Credentials.from_generated_secret(
                "ops_admin", secret_name=f"{project}/db/ops_admin"),
            backup_retention=Duration.days(1), deletion_protection=False,
            removal_policy=RemovalPolicy.SNAPSHOT,  # teardown chooses snapshot explicitly
        )

        # ---- queue -----------------------------------------------------------------------
        dlq = sqs.Queue(self, "JobsDlq", retention_period=Duration.days(14),
                        encryption=sqs.QueueEncryption.SQS_MANAGED)
        queue = sqs.Queue(self, "JobsQueue", retention_period=Duration.days(4),
                          visibility_timeout=Duration.seconds(180),
                          encryption=sqs.QueueEncryption.SQS_MANAGED,
                          dead_letter_queue=sqs.DeadLetterQueue(queue=dlq, max_receive_count=5))

        # ---- identity --------------------------------------------------------------------
        pool = cognito.UserPool(self, "UserPool", self_sign_up_enabled=False,
                                sign_in_aliases=cognito.SignInAliases(username=True),
                                account_recovery=cognito.AccountRecovery.NONE,
                                password_policy=cognito.PasswordPolicy(min_length=14),
                                removal_policy=RemovalPolicy.DESTROY)
        client = pool.add_client(
            "WebClient", generate_secret=False,
            auth_flows=cognito.AuthFlow(admin_user_password=True),
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True),
                scopes=[cognito.OAuthScope.OPENID, cognito.OAuthScope.PROFILE],
                callback_urls=[f"https://{domain}/auth/callback"],
                logout_urls=[f"https://{domain}/"]),
            prevent_user_existence_errors=True,
            access_token_validity=Duration.hours(1), id_token_validity=Duration.hours(1))
        prefix = f"{project}-{hashlib.sha256(domain.encode()).hexdigest()[:8]}"
        pool_domain = pool.add_domain("HostedUi", cognito_domain=cognito.CognitoDomainOptions(
            domain_prefix=prefix))

        # ---- storage, registry, logs ----------------------------------------------------
        bucket = s3.Bucket(self, "Data", versioned=True, encryption=s3.BucketEncryption.S3_MANAGED,
                           block_public_access=s3.BlockPublicAccess.BLOCK_ALL, enforce_ssl=True,
                           removal_policy=RemovalPolicy.DESTROY, auto_delete_objects=True,
                           lifecycle_rules=[
                               s3.LifecycleRule(prefix="staging/",
                                                expiration=Duration.days(cfg["staging_expiry_days"])),
                               s3.LifecycleRule(noncurrent_version_expiration=Duration.days(30)),
                           ])
        repo = ecr.Repository(self, "Repo", repository_name=project,
                              removal_policy=RemovalPolicy.DESTROY, empty_on_delete=True,
                              lifecycle_rules=[ecr.LifecycleRule(max_image_count=5)])
        log_groups = {name: logs.LogGroup(self, f"{name.title()}Logs",
                                          log_group_name=f"/{project}/{name}",
                                          retention=retention,
                                          removal_policy=RemovalPolicy.DESTROY)
                      for name in ("api", "worker", "tasks")}

        # ---- ECS -------------------------------------------------------------------------
        cluster = ecs.Cluster(self, "Cluster", vpc=vpc)
        image = ecs.ContainerImage.from_ecr_repository(repo, tag=image_tag)
        platform = ecs.RuntimePlatform(cpu_architecture=ecs.CpuArchitecture.ARM64,
                                       operating_system_family=ecs.OperatingSystemFamily.LINUX)
        common_env = {
            "DEPLOY_ENV": "aws", "AUTH_MODE": "cognito", "AWS_REGION": self.region,
            "OPS_DB_HOST": db.db_instance_endpoint_address, "OPS_DB_NAME": "ops",
            "COGNITO_USER_POOL_ID": pool.user_pool_id,
            "COGNITO_CLIENT_ID": client.user_pool_client_id,
        }

        def creds(role: str, secret: sm.ISecret) -> tuple[dict, dict]:
            """Fixed role name in plain env; the password injected from Secrets Manager."""
            return ({f"OPS_DB_{role}_USER": f"ops_{role.lower()}"},
                    {f"OPS_DB_{role}_PASSWORD": ecs.Secret.from_secrets_manager(secret,
                                                                                 "password")})

        def task_def(name: str, cpu: int, mem: int, role: iam.Role) -> ecs.FargateTaskDefinition:
            return ecs.FargateTaskDefinition(self, f"{name}Task", cpu=cpu, memory_limit_mib=mem,
                                             runtime_platform=platform, task_role=role)

        # API: S3 read and export, its own secret, logs. No Bedrock, no queue send.
        api_role = iam.Role(self, "ApiTaskRole",
                            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"))
        bucket.grant_read(api_role, "imports/*")
        bucket.grant_read_write(api_role, "exports/*")
        api_env, api_sec = creds("API", api_secret)
        api_task = task_def("Api", sizing["api"]["cpu"], sizing["api"]["memory_mib"], api_role)
        api_task.add_container(
            "api", image=image, environment={**common_env, **api_env}, secrets=api_sec,
            logging=ecs.LogDriver.aws_logs(stream_prefix="api", log_group=log_groups["api"]),
            port_mappings=[ecs.PortMapping(container_port=8000)],
            command=["uvicorn", "ops.api:app", "--host", "0.0.0.0", "--port", "8000",
                     "--no-access-log"])

        # Worker: queue send/receive/delete, its own secret, configured Bedrock models.
        worker_role = iam.Role(self, "WorkerTaskRole",
                               assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"))
        queue.grant_consume_messages(worker_role)
        queue.grant_send_messages(worker_role)
        model_ids = [models["default_model_id"], models["second_model_id"]]
        model_region = models["region"]  # Bedrock runs in us-east-1 even when the stack does not
        resources = []
        for mid in model_ids:
            base = foundation_model_id(mid)
            resources += [f"arn:aws:bedrock:{model_region}::foundation-model/{base}",
                          f"arn:aws:bedrock:*::foundation-model/{base}",
                          f"arn:aws:bedrock:::foundation-model/{base}"]
            if base != mid:
                resources.append(f"arn:aws:bedrock:{model_region}:{self.account}:"
                                 f"inference-profile/{mid}")
        worker_role.add_to_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel"], resources=sorted(set(resources))))
        worker_env, worker_sec = creds("WORKER", worker_secret)
        worker_task = task_def("Worker", sizing["worker"]["cpu"], sizing["worker"]["memory_mib"],
                               worker_role)
        worker_task.add_container(
            "worker", image=image,
            environment={**common_env, **worker_env, "OPS_QUEUE_URL": queue.queue_url},
            secrets=worker_sec,
            logging=ecs.LogDriver.aws_logs(stream_prefix="worker",
                                           log_group=log_groups["worker"]),
            command=["ops", "worker", "--queue", "sqs", "--provider", "bedrock"])

        # One-off migration task: its own role; master credentials plus role passwords.
        mig_role = iam.Role(self, "MigrationTaskRole",
                            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"))
        mig_task = task_def("Migration", 256, 512, mig_role)
        mig_task.add_container(
            "migrate", image=image,
            environment={**common_env, "OPS_BOOTSTRAP_ROLES": "1",
                         "OPS_DB_ADMIN_USER": "ops_admin"},
            secrets={"OPS_DB_ADMIN_PASSWORD": ecs.Secret.from_secrets_manager(db.secret,
                                                                               "password"),
                     **{f"OPS_DB_{r}_PASSWORD": ecs.Secret.from_secrets_manager(s, "password")
                        for r, s in (("IMPORT", import_secret), ("API", api_secret),
                                     ("WORKER", worker_secret))}},
            logging=ecs.LogDriver.aws_logs(stream_prefix="migration",
                                           log_group=log_groups["tasks"]),
            command=["ops", "migrate"])

        # One-off import task: reads imports/ from S3; import role credentials.
        imp_role = iam.Role(self, "ImportTaskRole",
                            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"))
        bucket.grant_read(imp_role, "imports/*")
        imp_env, imp_sec = creds("IMPORT", import_secret)
        imp_task = task_def("Import", 1024, 2048, imp_role)
        imp_task.add_container(
            "import", image=image, environment={**common_env, **imp_env}, secrets=imp_sec,
            logging=ecs.LogDriver.aws_logs(stream_prefix="import", log_group=log_groups["tasks"]),
            command=["ops", "data", "validate"])

        # One-off seeding task: admin credentials, Cognito user admin, demo-users secret.
        seed_role = iam.Role(self, "SeedTaskRole",
                             assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"))
        seed_role.add_to_policy(iam.PolicyStatement(
            actions=["cognito-idp:AdminCreateUser", "cognito-idp:AdminSetUserPassword",
                     "cognito-idp:AdminGetUser"], resources=[pool.user_pool_arn]))
        demo_users_secret.grant_write(seed_role)
        seed_task = task_def("Seed", 256, 512, seed_role)
        seed_task.add_container(
            "seed", image=image,
            environment={**common_env, "OPS_DB_ADMIN_USER": "ops_admin",
                         "OPS_DEMO_USERS_SECRET": demo_users_secret.secret_name},
            secrets={"OPS_DB_ADMIN_PASSWORD": ecs.Secret.from_secrets_manager(db.secret,
                                                                               "password")},
            logging=ecs.LogDriver.aws_logs(stream_prefix="seed", log_group=log_groups["tasks"]),
            command=["ops", "seed-users", "--mode", "aws"])

        public = ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC)
        desired = 1 if services_running else 0
        api_service = ecs.FargateService(
            self, "ApiService", cluster=cluster, task_definition=api_task, desired_count=desired,
            assign_public_ip=True, vpc_subnets=public, security_groups=[api_sg],
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
            min_healthy_percent=0, max_healthy_percent=200)
        ecs.FargateService(
            self, "WorkerService", cluster=cluster, task_definition=worker_task,
            desired_count=desired, assign_public_ip=True, vpc_subnets=public,
            security_groups=[worker_sg],
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
            min_healthy_percent=0, max_healthy_percent=100)

        # ---- load balancer and DNS -----------------------------------------------------
        alb = elbv2.ApplicationLoadBalancer(self, "Alb", vpc=vpc, internet_facing=True,
                                            security_group=alb_sg, vpc_subnets=public)
        cert = acm.Certificate.from_certificate_arn(self, "Cert", certificate_arn)
        https = alb.add_listener("Https", port=443, certificates=[cert],
                                 ssl_policy=elbv2.SslPolicy.RECOMMENDED_TLS, open=False)
        alb.add_redirect(source_port=80, target_port=443, open=False)
        https.add_targets("Api", port=8000, protocol=elbv2.ApplicationProtocol.HTTP,
                          targets=[api_service],
                          health_check=elbv2.HealthCheck(path="/api/health",
                                                         healthy_http_codes="200"),
                          deregistration_delay=Duration.seconds(10))
        if cfg.get("hosted_zone_name"):
            zone = r53.HostedZone.from_lookup(self, "Zone", domain_name=cfg["hosted_zone_name"])
            r53.ARecord(self, "Alias", zone=zone, record_name=domain,
                        target=r53.RecordTarget.from_alias(r53_targets.LoadBalancerTarget(alb)))

        # ---- alarms ----------------------------------------------------------------------
        cw.Alarm(self, "DlqNotEmpty", metric=dlq.metric_approximate_number_of_messages_visible(),
                 threshold=0, evaluation_periods=1,
                 comparison_operator=cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
                 alarm_description="Messages reached the DLQ; inspect, never redrive blindly")
        cw.Alarm(self, "QueueBacklogAge",
                 metric=queue.metric_approximate_age_of_oldest_message(),
                 threshold=300, evaluation_periods=2,
                 comparison_operator=cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
                 alarm_description="Oldest job message older than 5 minutes")

        # ---- outputs (consumed by scripts; not committed) ---------------------------
        outputs = {
            "AlbDnsName": alb.load_balancer_dns_name, "ClusterName": cluster.cluster_name,
            "UserPoolId": pool.user_pool_id, "UserPoolClientId": client.user_pool_client_id,
            "CognitoDomain": pool_domain.base_url(), "QueueUrl": queue.queue_url,
            "DlqUrl": dlq.queue_url, "BucketName": bucket.bucket_name,
            "RepositoryUri": repo.repository_uri, "DbEndpoint": db.db_instance_endpoint_address,
            "MigrationTaskDef": mig_task.task_definition_arn,
            "ImportTaskDef": imp_task.task_definition_arn,
            "SeedTaskDef": seed_task.task_definition_arn,
            "OneOffTaskSg": task_sg.security_group_id,
            "PublicSubnets": ",".join(s.subnet_id for s in vpc.public_subnets),
            "DemoUsersSecret": demo_users_secret.secret_name,
        }
        for key, value in outputs.items():
            CfnOutput(self, f"Out{key}", value=value, export_name=None)
