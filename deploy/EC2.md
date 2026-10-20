# Deploying on one EC2 instance

One small instance runs the app and Caddy (automatic HTTPS). Voice needs
HTTPS because browsers only allow the microphone on secure pages. A free
`sslip.io` hostname means you don't need to buy a domain.

Not Lambda: a voice call is one long-lived process holding an audio stream,
which Lambda cannot do.

## 1. Before you start

- Bedrock: in the Bedrock console for your region, check **Model access**
  shows Nova 2 Lite as granted.
- Sarvam: an API key from dashboard.sarvam.ai, with some credit on it.
- Cost guard: create a $5 monthly budget alert in AWS Billing.

## 2. IAM role for the instance

Create a role for EC2 with this policy (replace `ACCOUNT_ID`; keep the
region matching `AWS_REGION`). The app gets Bedrock access from the role,
so no AWS keys are ever stored on the server.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "InvokeNova",
      "Effect": "Allow",
      "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
      "Resource": [
        "arn:aws:bedrock:*::foundation-model/amazon.nova-2-lite-v1:0",
        "arn:aws:bedrock:ap-south-1:ACCOUNT_ID:inference-profile/global.amazon.nova-2-lite-v1:0"
      ]
    }
  ]
}
```

## 3. Launch the instance

- Ubuntu 24.04, **t3.small** (2 GB), 16 GB disk, in the same region as Bedrock.
- Attach the IAM role from step 2.
- Security group, inbound:

  | Port | Protocol | From | Why |
  | --- | --- | --- | --- |
  | 22 | TCP | your IP only | SSH |
  | 80 | TCP | anywhere | HTTPS certificate challenge and redirect |
  | 443 | TCP | anywhere | the app |
  | 1024–65535 | UDP | anywhere | WebRTC audio (only the app listens on these) |

- Allocate an Elastic IP so the address (and the hostname) stays the same.

## 4. Install and run

```bash
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2 git
sudo usermod -aG docker $USER && newgrp docker

git clone <your repo> vaani && cd vaani
cp .env.example .env
nano .env
```

In `.env` set at least:

```
ENVIRONMENT=production
ALLOWED_HOSTS=13-234-56-78.sslip.io        # your Elastic IP with dashes
AWS_REGION=ap-south-1
SARVAM_API_KEY=<your key>
```

Then:

```bash
DOMAIN=13-234-56-78.sslip.io docker compose up -d --build
docker compose logs -f vaani      # "Vaani started (production); voice on"
```

Before the first start, give yourself (and anyone you invite) a sign-in. On your
laptop, run `python -m server.users <user_id>` for each person, paste the printed
lines into `USERS` in `server/users.py`, commit and pull on the server. The hashes
are safe to commit; the passwords never leave your laptop.

Open `https://13-234-56-78.sslip.io`, sign in, and make a call.

## 5. Day to day

- **Stop when not in use:** `docker compose stop` (or stop the instance).
  Start again before you send the link.
- **Audit log:** `docker compose exec vaani tail -f var/audit.jsonl`
  (phones, DOBs and OTPs are masked).
- **Update:** `git pull && DOMAIN=... docker compose up -d --build`.
- **Callers on strict office networks** may not connect audio over UDP. Set
  `TURN_URL`, `TURN_USERNAME`, `TURN_PASSWORD` for a TURN relay (for example
  a free tier from a TURN provider), or use typing mode.

## What protects the bill

| Limit | Default | Setting |
| --- | --- | --- |
| Sign-in for everything | required in production | `server/users.py` |
| Voice calls at the same time | 3 | `MAX_CONCURRENT_VOICE_CALLS` |
| New calls per network per hour | 12 | `CALLS_PER_IP_PER_HOUR` |
| Calls per day, everyone together | 150 | `DAILY_CALL_BUDGET` |
| Longest call | 10 minutes | `CALL_MAX_SECONDS` |
| Silence before hang-up | 90 seconds | `CALL_IDLE_SECONDS` |
| Caller turns per call | 60 | `MAX_TURNS_PER_CALL` |
| Typed messages per call per minute | 20 | `TEXT_TURNS_PER_MINUTE` |
| Agent steps per turn | about 5 model calls | fixed in `agent/graph.py` |
