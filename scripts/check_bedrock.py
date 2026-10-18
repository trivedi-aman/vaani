"""
Check that this machine can reach Amazon Nova on Bedrock with the settings
in .env, before starting the server.

    python -m scripts.check_bedrock
"""
import sys

from core.config import get_settings


def main() -> int:
    s = get_settings()
    source = f"profile '{s.aws_profile}'" if s.aws_profile else "the default AWS credentials"
    print(f"Calling {s.nova_model_id} in {s.aws_region} using {source}...")
    try:
        from agent.llm import bedrock_model
        reply = bedrock_model(s).invoke("Reply with the single word: ready")
    except Exception as e:  # report every failure in plain words
        name, text = type(e).__name__, str(e)
        print(f"\nFailed: {name}: {text[:300]}")
        if "ProfileNotFound" in name or "could not be found" in text:
            print("Fix: run `aws configure --profile <name>` and set AWS_PROFILE to that name in .env.")
        elif "NoCredentials" in name or "Unable to locate credentials" in text:
            print("Fix: set AWS_PROFILE in .env, or run `aws configure`.")
        elif "AccessDenied" in text or "not authorized" in text:
            print("Fix: the IAM user needs bedrock:InvokeModel on Nova (policy in deploy/EC2.md), "
                  "and Nova 2 Lite must be enabled under Bedrock > Model access in this region.")
        elif "ValidationException" in name or "model identifier is invalid" in text or "inference profile" in text:
            print("Fix: the model ID or region is wrong. Try AWS_REGION=us-east-1 with "
                  "NOVA_MODEL_ID=us.amazon.nova-2-lite-v1:0.")
        return 1
    print(f"OK. Nova said: {reply.content if isinstance(reply.content, str) else reply.text}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
