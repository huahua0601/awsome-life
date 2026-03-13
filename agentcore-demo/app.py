#!/usr/bin/env python3
"""AgentCore Demo — CDK Application entry point.

Deploys a Strands Agent on AgentCore Runtime with Claude Opus 4.6.
"""

import os
import aws_cdk as cdk
from stacks.agentcore_stack import AgentCoreStack

app = cdk.App()

env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=os.environ.get("CDK_DEFAULT_REGION", "us-west-2"),
)

AgentCoreStack(app, "AgentCoreDemoStack", env=env)

app.synth()
