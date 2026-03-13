"""AgentCore CDK Stack — deploys a Strands Agent via S3 direct code deployment.

Resources:
  - S3 Bucket for deployment package
  - S3 BucketDeployment to upload the zip
  - IAM execution role (Bedrock invoke, S3 read, CloudWatch, X-Ray)
  - AgentCore CfnRuntime (S3 code configuration)
  - AgentCore CfnRuntimeEndpoint
"""

import os

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    aws_bedrockagentcore as agentcore,
    aws_iam as iam,
    aws_s3 as s3,
    aws_s3_deployment as s3deploy,
)
from constructs import Construct


class AgentCoreStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        region = Stack.of(self).region
        account = Stack.of(self).account

        model_id = self.node.try_get_context("model_id") or "global.anthropic.claude-opus-4-6-v1"
        runtime_name = self.node.try_get_context("runtime_name") or "claude_opus_agent"

        # --- S3 Bucket for deployment package ----------------------------------
        code_bucket = s3.Bucket(
            self,
            "AgentCodeBucket",
            bucket_name=f"agentcore-demo-code-{account}-{region}",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
        )

        # Upload the pre-built zip from local dist/ directory
        deployment = s3deploy.BucketDeployment(
            self,
            "DeployAgentCode",
            sources=[s3deploy.Source.asset(os.path.join(os.path.dirname(__file__), "..", "dist"))],
            destination_bucket=code_bucket,
            destination_key_prefix=runtime_name,
        )

        # --- IAM Execution Role ------------------------------------------------
        execution_role = iam.Role(
            self,
            "AgentCoreExecutionRole",
            assumed_by=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
            description="Execution role for AgentCore Runtime (S3 code deploy) with Claude Opus 4.6",
        )

        # Bedrock model invocation
        execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="BedrockModelInvocation",
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                    "bedrock:Converse",
                    "bedrock:ConverseStream",
                ],
                resources=[
                    "arn:aws:bedrock:*::foundation-model/*",
                    f"arn:aws:bedrock:*:{account}:inference-profile/*",
                ],
            )
        )

        # S3 read access for deployment package
        code_bucket.grant_read(execution_role)

        # CloudWatch Logs
        execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="CloudWatchLogs",
                actions=[
                    "logs:DescribeLogGroups",
                    "logs:DescribeLogStreams",
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                resources=[
                    f"arn:aws:logs:{region}:{account}:log-group:/aws/bedrock-agentcore/runtimes/*",
                    f"arn:aws:logs:{region}:{account}:log-group:/aws/bedrock-agentcore/runtimes/*:log-stream:*",
                ],
            )
        )

        # CloudWatch Metrics
        execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="CloudWatchMetrics",
                actions=["cloudwatch:PutMetricData"],
                resources=["*"],
                conditions={
                    "StringEquals": {
                        "cloudwatch:namespace": "bedrock-agentcore"
                    }
                },
            )
        )

        # X-Ray tracing
        execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="XRayTracing",
                actions=[
                    "xray:PutTraceSegments",
                    "xray:PutTelemetryRecords",
                    "xray:GetSamplingRules",
                    "xray:GetSamplingTargets",
                ],
                resources=["*"],
            )
        )

        # --- AgentCore Runtime (S3 code deployment) ----------------------------
        runtime = agentcore.CfnRuntime(
            self,
            "AgentCoreRuntime",
            agent_runtime_name=runtime_name,
            agent_runtime_artifact=agentcore.CfnRuntime.AgentRuntimeArtifactProperty(
                code_configuration=agentcore.CfnRuntime.CodeConfigurationProperty(
                    code=agentcore.CfnRuntime.CodeProperty(
                        s3=agentcore.CfnRuntime.S3LocationProperty(
                            bucket=code_bucket.bucket_name,
                            prefix=f"{runtime_name}/deployment_package.zip",
                        )
                    ),
                    entry_point=["main.py"],
                    runtime="PYTHON_3_13",
                )
            ),
            network_configuration=agentcore.CfnRuntime.NetworkConfigurationProperty(
                network_mode="PUBLIC",
            ),
            role_arn=execution_role.role_arn,
            environment_variables={
                "BEDROCK_MODEL_ID": model_id,
            },
            description=f"AgentCore Runtime (S3 code deploy) — Strands Agent with {model_id}",
            lifecycle_configuration=agentcore.CfnRuntime.LifecycleConfigurationProperty(
                idle_runtime_session_timeout=300,
                max_lifetime=1800,
            ),
        )
        runtime.node.add_dependency(execution_role)
        runtime.node.add_dependency(deployment)

        # --- AgentCore Runtime Endpoint ----------------------------------------
        endpoint = agentcore.CfnRuntimeEndpoint(
            self,
            "AgentCoreRuntimeEndpoint",
            agent_runtime_id=runtime.attr_agent_runtime_id,
            name=f"{runtime_name}_endpoint",
            description="Endpoint for Claude Opus 4.6 Agent",
            agent_runtime_version=runtime.attr_agent_runtime_version,
        )
        endpoint.add_dependency(runtime)

        # --- Outputs -----------------------------------------------------------
        CfnOutput(self, "RuntimeId", value=runtime.attr_agent_runtime_id)
        CfnOutput(self, "RuntimeEndpointId", value=endpoint.attr_id)
        CfnOutput(self, "CodeBucketName", value=code_bucket.bucket_name)
        CfnOutput(
            self,
            "RuntimeArn",
            value=f"arn:aws:bedrock-agentcore:{region}:{account}:runtime/{runtime.attr_agent_runtime_id}",
        )
