# Pre-deployment security review

Review date: 2026-10-19

## Security findings

### HIGH — OTP is exposed through the caller's own call session

**Affected code:** `agent/tools.py` (OTP issuance) and `server/app.py` (authenticated call-event stream).

The verification flow emits the OTP as an `otp` event into the call session. The event stream is authenticated with the caller's call token, and the frontend displays the code in its simulated-phone UI. As a result, a caller who supplies a customer's name and one matching identifier (date of birth, phone number, or loan ID) can retrieve the OTP from their own session and satisfy the second-factor check without controlling the customer's registered phone.

The repository describes the OTP delivery as simulated and the customer data as demo data. This is a release blocker if the system is connected to real customer records or used to protect real customer data.

**Recommendation:** Deliver OTPs only through an independent, verified channel. Do not expose the code in call events, model/tool results, browser UI, or logs, and disable simulated OTP delivery in production.

## Other deployment concerns

- Call-created tickets, requests, and notes are held in process memory and are lost on restart. They are not a durable system of record.
- The README states that live Bedrock/Sarvam credentials and real recordings have not been tested end to end. Complete integration and voice-flow testing before production deployment.
- The README also notes that multiple server instances require shared Redis/database-backed state, and networks that block UDP require a TURN relay or typing mode.

## Scope and limitations

This review is based on the repository state reviewed on the date above. Findings describe risks in the current demo architecture; production configuration, real data handling, and deployment infrastructure should be reviewed separately before launch.
