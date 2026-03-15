### Feature: Implement Mailgun Email Service via Kafka

**Problem**
The FluentMeet application needs to send transactional emails for user account verification, password reset, and other notifications. Currently, no email service is integrated. Directly calling a third-party email API synchronously inside request handlers would increase latency and couple the request lifecycle to an external service, creating a poor user experience if the provider is slow or unavailable.

**Proposed Solution**
Integrate Mailgun as the email provider and decouple email sending from the HTTP request lifecycle using Apache Kafka. When an email needs to be sent, the application will publish a structured message to a Kafka topic (`notifications.email`). A dedicated consumer worker will pick up the message and dispatch it via the Mailgun REST API. This approach makes email sending asynchronous, resilient, and independently scalable.

**User Stories**
*   **As a new user,** I want to receive a verification email immediately after signing up, so I can activate my account without experiencing delays in the registration response.
*   **As a user,** I want to receive a password reset email when I request one, so I can regain access to my account.
*   **As a developer,** I want a reusable, Kafka-backed email service so that any part of the system can trigger an email without being blocked by the Mailgun API call.
*   **As a DevOps engineer,** I want email failures to be retried automatically and logged clearly, so transient Mailgun outages don't result in silently dropped emails.

**Acceptance Criteria**
1.  A `Mailgun` configuration block (API key, domain, sender address) is defined in `app/core/config.py` and sourced from environment variables — never hardcoded.
2.  A Kafka topic `notifications.email` is created and documented in the infrastructure setup.
3.  An `EmailProducerService` is implemented with a `send_email(to, subject, html_body, template_data)` method that publishes a structured JSON message to the `notifications.email` Kafka topic.
4.  An `EmailConsumerWorker` is implemented to:
    *   Consume messages from the `notifications.email` topic.
    *   Call the Mailgun REST API (`/messages`) to deliver the email.
    *   Log success and failure outcomes.
    *   Handle retries on transient failures using Kafka consumer group offsets.
5.  Email templates are implemented for:
    *   **Account Verification**: Contains the verification link.
    *   **Password Reset**: Contains the time-limited reset link.
6.  The `EmailProducerService` is injected into and called from the user registration and password reset flows.
7.  Unit tests verify that the producer publishes the correct message payload to the Kafka topic.
8.  Integration tests verify the full flow: producer publishes → consumer dispatches → Mailgun API is called.

**Proposed Technical Details**
*   **Mailgun SDK**: Use the `mailgun2` library (already in `requirements.txt`) or direct `httpx` calls to the Mailgun `/messages` endpoint.
*   **Kafka Topic**: `notifications.email` — messages follow a standard envelope:
    ```json
    {
      "to": "user@example.com",
      "subject": "Verify your FluentMeet account",
      "template": "verification",
      "data": { "verification_link": "https://..." }
    }
    ```
*   **Producer**: `app/services/email_producer.py` — uses `aiokafka.AIOKafkaProducer` to publish messages asynchronously.
*   **Consumer Worker**: `app/services/email_consumer.py` — long-running `aiokafka.AIOKafkaConsumer` in a background task, started via FastAPI `lifespan` events.
*   **Templates**: Jinja2 HTML templates stored in `app/templates/email/` (e.g., `verification.html`, `password_reset.html`).
*   **Config**: New fields in `app/core/config.py`:
    ```python
    MAILGUN_API_KEY: str
    MAILGUN_DOMAIN: str
    MAILGUN_FROM_ADDRESS: str = "no-reply@fluentmeet.com"
    ```

**Tasks**
- [ ] Add `MAILGUN_API_KEY`, `MAILGUN_DOMAIN`, and `MAILGUN_FROM_ADDRESS` to `.env.example` and `app/core/config.py`.
- [ ] Create the `notifications.email` Kafka topic and document it in `infra/`.
- [ ] Implement `EmailProducerService` in `app/services/email_producer.py`.
- [ ] Implement `EmailConsumerWorker` in `app/services/email_consumer.py`.
- [ ] Register the consumer as a background task in the FastAPI `lifespan` context manager in `app/main.py`.
- [ ] Create Jinja2 HTML templates for verification and password reset emails.
- [ ] Integrate the email producer into the user registration endpoint (`POST /api/v1/auth/signup`).
- [ ] Integrate the email producer into the password reset endpoint (`POST /api/v1/auth/forgot-password`).
- [ ] Write unit tests for the `EmailProducerService` (mock the Kafka producer).
- [ ] Write integration tests for the full consumer → Mailgun dispatch flow (mock the Mailgun API).

**Open Questions/Considerations**
*   What is the retry strategy for failed Mailgun deliveries — dead-letter queue or fixed retry count?
*   Should email sending failures be surfaced to the user (e.g., "email failed to send, please try again") or handled silently with a background retry?
*   What is the Kafka consumer group ID for the email worker, and how should it be managed across deployments?
*   Should we implement a resend-verification endpoint for users whose verification tokens have expired?
