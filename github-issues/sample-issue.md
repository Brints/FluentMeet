### Feature: Implement Email Service for User Account Verification

**Problem**
The user registration process requires email verification to ensure users provide a valid and accessible email address. However, the application currently lacks the functionality to send emails, making it impossible to send verification tokens or links to new users.

**Proposed Solution**
Integrate a robust email sending service into the application using the Spring Boot Mail starter. This will involve creating a generic `EmailService` that can be configured to use an SMTP server or a third-party email provider (e.g., SendGrid, Mailgun). This service will be used to send a welcome email containing a unique, time-sensitive verification link to users upon registration.

**User Stories**
*   **As a new user,** I want to receive an email with a verification link after I sign up, so I can confirm ownership of my email account and activate my user account.
*   **As a developer,** I want a centralized and reusable `EmailService` so that I can easily send various types of transactional emails (e.g., password resets, notifications) in the future.

**Acceptance Criteria**
1.  An `EmailService` is implemented and integrated into the application.
2.  Email provider credentials (e.g., SMTP host, port, username, password) are externalized in the application's configuration files (`application.properties` or `application.yml`) and are not hardcoded.
3.  Upon successful user registration, the system generates a unique verification token, saves it, and associates it with the new user.
4.  The `EmailService` is called to send a verification email to the user's provided email address. The email body must contain the verification link.
5.  The user's account is marked as `UNVERIFIED` until they click the verification link.
6.  A new public endpoint (e.g., `GET /api/v1/auth/verify?token=...`) is created to handle the verification process.
7.  When a user clicks the link, the endpoint validates the token, marks the user's account as `VERIFIED`, and invalidates the token to prevent reuse.
8.  Email sending should be performed asynchronously to avoid blocking the user registration HTTP request.

**Proposed Technical Details**
*   **Dependency:** Add the `spring-boot-starter-mail` dependency to the `pom.xml`.
*   **Configuration:** Configure Spring Mail properties in `application.properties`. For development, a tool like Mailtrap or a local SMTP server can be used.
*   **Service:** Create an `EmailService` with a method like `sendHtmlEmail(String to, String subject, String htmlBody)`. Annotate the sending method with `@Async` for non-blocking execution.
*   **Entity:** Create a `VerificationToken` entity to store the token, its expiry date, and a `@OneToOne` relationship to the `User` entity.
*   **Templating:** Use a templating engine like Thymeleaf to create a professional HTML email template for the verification message.
*   **Controller:** Add a new method in an `AuthController` or a dedicated `VerificationController` to handle the `GET /api/v1/auth/verify` request.

**Tasks**
- [ ] Add `spring-boot-starter-mail` and `spring-boot-starter-thymeleaf` to `pom.xml`.
- [ ] Configure mail server settings in `application.properties`.
- [ ] Implement the `EmailService` and enable asynchronous processing with `@EnableAsync`.
- [ ] Create the `VerificationToken` entity, repository, and service.
- [ ] Design and create the HTML email template (`verification-email.html`).
- [ ] Update the user registration logic to generate a token and trigger the email sending process.
- [ ] Implement the verification endpoint (`GET /api/v1/auth/verify`) to validate the token and activate the user.
- [ ] Write unit and integration tests for token generation, email sending, and the verification flow.

**Open Questions/Considerations**
*   Which email service provider (SendGrid, AWS SES, Mailgun) will be used in production?
*   What should be the expiration time for verification tokens (e.g., 24 hours)?
*   How should the application handle cases where the email fails to send? Should there be a retry mechanism?
*   Should we provide an endpoint for users to request a new verification email if the original one expires or is lost?