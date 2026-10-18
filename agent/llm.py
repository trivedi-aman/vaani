"""The chat model: Amazon Nova on Bedrock, with retries for throttling and a hard timeout."""
from botocore.config import Config
from langchain_aws import ChatBedrockConverse

from core.config import Settings


def bedrock_model(settings: Settings) -> ChatBedrockConverse:
    """
    Credentials come from boto3's default chain: an IAM role on EC2, or AWS_*
    variables locally. "adaptive" retry mode backs off when Bedrock throttles.
    """
    return ChatBedrockConverse(
        model=settings.nova_model_id,
        region_name=settings.aws_region,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        config=Config(
            retries={"mode": "adaptive", "max_attempts": 3},
            connect_timeout=5,
            read_timeout=settings.llm_timeout_seconds,
        ),
    )
