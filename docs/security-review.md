# Security review (2026-11-24)

**Status: findings and suggestions, none adopted.** The owner's decision, 2026-11-24: "While still in
development locally, there is no need for enhanced security. Instead create a security review document
and add these suggestions." So nothing here is built. Section 2 is what was found in the setup as it is
used now, each with the fix suggested. Section 4 is what a hosted platform would need, chosen for this
project from the published guidance cited in section 6. Section 5 is the order to adopt them in.

The fixes for findings 1 to 4 were written, tested and then taken back out, at the owner's word. They are
kept in this repository's history as commit `74c8c2d` (pull request #17, before its last commit), with their
tests, and can be brought back from there (`git show 74c8c2d`) when they are wanted.

## 1. What was reviewed, and how

The stack as the household uses it after the per-household migration (`docs/verification-and-sharing.md`
§3.4a): phones on the home network over HTTPS (port 8443, `docs/pages.md`), port 8085 open to the network
over plain HTTP by the owner's choice (2026-11-22), households kept apart by Structr's own grants
(`docs/methods.md`), the pages and their bookings, the methods, the files the pages load, and the tools.

Read from the code and from Structr 7.1.0's own classes (its Docker image), and tried on a throwaway
Structr 7.1 rebuilt from the scripts in a cloud session, never on the owner's instance. "Live" below
means tried there. The places to start that `docs/todo.md` listed were each looked at.

## 2. Findings

Ranked for the setup as it is today: one household, on a home network, behind a firewall.

| # | Finding | Rank | Suggested fix |
|---|---|---|---|
| 1 | **A page on another site can book through a signed-in browser.** A booking is a link (`?do=...&token=...`) and the token is any hex string, not tied to the session. Structr's session cookie is `SameSite=Lax`, which a browser sends with a link followed from another site. Live: a purchase sent with the session cookie alone and `Sec-Fetch-Site: cross-site` booked. A purchase needs no node id to forge; a use or discard needs one | High once anyone signs in from a phone that also browses the web | Book only what the browser says came from one of the instance's own pages: `Sec-Fetch-Site: same-origin` (every current browser sends it), else a `Referer` naming this host, else refuse. Requests signed in by their own headers (the tools' `X-User`, a session token as `X-StructrSessionToken`) carry no cookie a browser added and need no check. Structr 7.1 offers `$.getRequestHeader` to page scripts (live). Written and tried live in `74c8c2d`: refused from another site, a bookmark or with no headers; booked from the page. Later, bookings as POSTs (the Lax cookie is not sent with a cross-site POST), with a token tied to the session as a fallback (OWASP CSRF cheat sheet) |
| 2 | **Development, throwaway and backup-check stacks answer the whole home network.** `docker-compose.yml` publishes Structr on every interface. A backup's check (`tools/backup.py verify`) restores the owner's data and accounts into one for its minutes | Medium | Publish on `127.0.0.1` unless told otherwise (`"${STRUCTR_BIND:-127.0.0.1}:${STRUCTR_PORT:-8083}:8082"`), with `tools/owner_stack.sh` passing its own `OWNER_BIND`, default `0.0.0.0`, so the owner's instance is unchanged until the owner changes it (in `74c8c2d`) |
| 3 | **Port 8085 takes passwords unencrypted from the network.** The pages' sign-in sends the password there even though the session cannot last (the cookie is `Secure`, and a browser drops it over plain HTTP from another device); Structr's admin interface and REST requests with `X-Password` send it too | Medium | The sign-in page sends nothing from an address that is neither HTTPS nor localhost, and says to use HTTPS (in `74c8c2d`). The whole of it: `OWNER_BIND=127.0.0.1`, so port 8085 answers only the computer, where the tools use it, and other devices reach the instance over HTTPS alone (the admin interface at `https://<address>:8443/structr`) |
| 4 | **Four wrong passwords lock an account** (`security.passwordpolicy.maxfailedattempts`, 4 in 7.1), so anyone on the network who knows a name can lock a household member out. `tools/create_login.py` sets a new password but leaves the account locked | Low | `create_login.py` also clears `passwordAttempts` (in `74c8c2d`). For the lock itself, see section 4.2: rate limiting in its place |
| 5 | **The admin interface is on the network,** on both ports. Structr 7.1 has no setting that limits it by address. The superuser's own lock (3 wrong passwords block it everywhere for 15 minutes) and the tools account's (4) stand between a guesser and everything | Low at home | Reach it only from the computer (an SSH tunnel from the laptop) once 8085 is closed; or Structr's second factor for admin accounts (`security.twofactorauthentication.level` 1, `isTwoFactorUser`). Hosted: section 4.3 |
| 6 | **Backups are plain archives on one computer,** holding the database (every password hash) and `private/` (the HTTPS key with it). Their folders end readable by other accounts on the computer (`0755`) | Low at home | Encrypt them (for example restic, or `age` over each archive) with a key kept off the computer, keep a copy elsewhere, and leave the folders `0700` once the containers have written them (check that `verify` and `restore` can still read them: the Neo4j container reads the dump as its own user) |
| 7 | **Any signed-in user may upload files** (`POST /structr/upload`), Structr's design | Low | Harmless as tried (below), but it takes disk. Limit the size (`uploadservlet.maxfilesize`), or refuse a non-admin's upload with a lifecycle rule on `File` (a schema change: a numbered script, run on the owner's instance, Structr restarted) |
| 8 | **The vendored barcode reader was trusted on its README's word** | Low | Checked: `pages/files/zxing-library-0.23.0.min.js` is byte for byte `@zxing/library` 0.23.0's `umd/index.min.js` from npm (the registry tarball's sha512 matches its published integrity). A test that pins its sha256 would catch any change (in `74c8c2d`) |
| 9 | **A failed booking prints the exception's own message** ("the booking failed: ..."), which can name Structr's internals | Low | Say what went wrong in plain words and log the detail; it fits the to-do item on the pages' help notes |

**Looked at and found sound.** A household member's REST requests answer 401 everywhere, the methods
included, since the owner's instance grants nothing but signing in (live); a member cannot make themselves
an admin (live, 401). Households read and book apart through the pages and the methods
(`tools/check_households.py`, live, including the pantry page's bookings by a member and the refusal of an
account in no household). Since the migration a page books as the member signed in; `$.doPrivileged` is
left only for adding a product (shared knowledge, the owner's rule) and on an instance with no household.
A member's upload lands in a folder no one else sees, cannot set `isTemplate` (Structr refuses it), cannot
reach the pages' folder (403), and Structr 7.1 serves an upload not made by an admin as a sandboxed
download, so it cannot run script on this site (all live). The pages escape what they print, and their data blocks
escape `<`. The sign-in page goes on only to the planner's own pages. Pages are sent
`X-Frame-Options: SAMEORIGIN` and `X-Content-Type-Options: nosniff` (live), and a page framed by another
site would be signed out (Lax). The Open Food Facts look-up sends only the barcode, with no cookie or
referrer. The StructrScript validators are built only from constants in the repository, and the one
Cypher a page runs is a constant. Neither the changelog nor the logs held a password after a member signed
in and uploaded (live). Structr 7.1 stores passwords with Argon2id (read from its classes). The HTTPS key
is `0600`, and its authority's key was deleted after signing. Neo4j is not published.

## 3. What changes with hosting

At home the attackers are few: a guest on the network, a web page a household member opens. Hosted, the
instance is on the internet, and the people signed in to it are strangers to each other. Three things
follow for this project in particular:

- **Households become tenants.** Keeping them apart is the first job (broken access control is first in
  the OWASP Top 10:2025). Here that rests entirely on Structr's grants: Neo4j Community has no roles, and
  every Neo4j user can do everything, so anything that reads Neo4j directly (the Python service or reading
  Bolt that `docs/architecture-decision.md` weighs) passes every household boundary and must enforce it
  itself.
- **The data is personal and close to health data:** each person's nutrition targets, exclusions,
  supplements and what they ate. Privacy law treats health data with extra care (the EU's GDPR Article 9;
  in the United States the FTC's Health Breach Notification Rule, extended to health apps in 2024, counts
  sharing such data without permission as a breach; other countries have their own).
- **Shared knowledge is written by strangers.** The owner's rule that a barcode one user saves is
  everyone's (2026-11-23) means one account can mislabel products for everybody.

## 4. Suggestions for a hosted platform

Measured against OWASP ASVS 5.0 (released May 2025) at **Level 2**, its middle level, meant for
applications that handle sensitive data such as this, and organised by the OWASP Top 10:2025. Each says what this project has
and what it would add.

### 4.1 Keeping households apart (A01 Broken Access Control)

- Deny by default: a household's nodes private to it (as `ownership.py` and the bookings already write
  them), shared knowledge read-only to members, every write through a method or page that checks who asks.
- Every way in tested for crossing households, on every release: grow `tools/check_households.py` from the
  pantry, week and request bookings to every method and page, including reading by id and listing, and run
  it before each deployment.
- No `$.doPrivileged` on what a user sent without the check written beside it, and a list of every
  privileged path in `docs/methods.md`, reviewed when one is added.
- Shared knowledge from users attributed (the Process already names who) and held for review, or kept to
  the household that wrote it until another confirms it, so one account cannot rewrite the catalogue for all.
- One household per instance is the limit today (`claimHousehold` refuses more): every writer must write
  privately itself before a second household is added (`docs/verification-and-sharing.md`).

### 4.2 Signing in and sessions (A07 Authentication Failures)

- Passwords as NIST SP 800-63B-4 (final, 2025) says: at least 15 characters where a password is the only
  factor (8 with a second factor), no rules about character kinds, checked against a list of breached and
  common passwords. Structr enforces length and complexity rules only (`security.passwordpolicy.complexity.*`),
  so the breach check would be the project's (at registration and on change).
- A second factor offered to everyone and required for admins: Structr has TOTP built in
  (`security.twofactorauthentication.*`, with trusted devices).
- Rate limiting on signing in instead of locking accounts: Structr 7.1's own limiter
  (`httpservice.ratelimiting.enabled`, 5 sign-ins a second per address by default, bursts of 10) slows
  guessing without letting strangers lock members out. Behind a reverse proxy it needs
  `httpservice.forwardedfor` to see real addresses, and only then.
- Self-registration, password reset and e-mail confirmation through Structr's own endpoints
  (`/structr/rest/registration`, `/reset-password`, both rate-limited), with SMTP configured.
- Sessions: the cookie `Secure`, `HttpOnly` and `SameSite` (Structr's defaults), an idle timeout (30 minutes
  now), sessions ended on a password change (`security.passwordpolicy.onchange.clearsessions`), a cap on
  sessions per user, and a way to sign out every device.
- Bookings safe from other sites (finding 1), as POSTs.

### 4.3 What is exposed (A02 Security Misconfiguration)

- Only HTTPS on 443 public. TLS ended either by Structr with a public certificate (its `letsencrypt`
  command fills the keystore) or by a reverse proxy in front (Caddy or nginx, which also renews
  certificates), set up with Mozilla's "intermediate" configuration.
- HSTS for a year (`max-age=31536000`) once HTTPS is certain; Structr sends 60 seconds today
  (`htmlservlet.customresponseheaders`). Plain HTTP only redirects (`httpservice.force.https`).
- The admin interface (`/structr/` beyond the pages and `/structr/rest/login`) and the configuration
  servlet not reachable from the internet: blocked at the proxy, reached over a VPN or SSH tunnel. One
  named admin account per operator, the superuser kept for emergencies, both with a second factor.
- Neo4j never published (as now). The health endpoint already answers only listed addresses.
- A Content Security Policy for the pages (scripts from the site only; the Open Food Facts look-up as the
  one `connect-src` elsewhere), on top of Structr's `X-Frame-Options` and `nosniff`.
- Containers with the memory caps they have, plus no new privileges, read-only file systems where Structr
  allows, and images pinned by digest (OWASP Docker Security cheat sheet). Structr's outbound requests
  limited to what scripts need (`application.httphelper.urlwhitelist`; `*` today).
- No defaults left: no `admin`/`admin` account (`STRUCTR_initialuser_create=false` and `48a`, as now),
  passwords generated at install (as `cloud/bootstrap.sh` does), kept in the host's secret store rather
  than a `.env` beside the code.

### 4.4 What the software is made of (A03 Software Supply Chain Failures, A08 Integrity Failures)

- Every dependency pinned: the images are (Structr 7.1.0, Neo4j 2025.12.1); the vendored reader pinned by
  hash (finding 8); the Python requirements pinned with hashes (`pip install --require-hashes`).
- Updates watched and applied on a schedule: Structr and Neo4j releases and advisories, the Java base
  image, the Python packages (`pip-audit`), with the upgrade runner of `docs/self-hosting.md` step 5.
- The repository's own guards kept on: GitHub secret scanning and Dependabot alerts, the pre-push hook.

### 4.5 Data at rest and in transit (A04 Cryptographic Failures)

- Passwords: Argon2id, Structr's (as now).
- The database and files on an encrypted disk or volume.
- Backups encrypted, copied off the host (three copies, two kinds of storage, one elsewhere), and restored
  into a throwaway on a schedule (`tools/backup.py verify` does the restore and the check today).
- Keys and certificates rotated, and kept out of backups that leave the host unencrypted.

### 4.6 Injection (A05)

- The rule the code keeps already, written down: never put what a user sent into Cypher, StructrScript or a
  shell command; find with `$.find` and a map; the validators built from constants only.
- `exec()` and scheduled jobs, if the planner service of `docs/self-hosting.md` step 3 uses them, given ids
  only, never free text.

### 4.7 Design for abuse (A06 Insecure Design)

- A short threat model kept with this file: a household member, another household, a stranger with an
  account, a stranger without one, and the operator; what each may reach.
- Quotas: uploads per household, recipes and products per day, and the planner's one solve at a time with
  a time limit per household (`docs/self-hosting.md`, "Security of the backend choices").

### 4.8 Knowing what happened (A09 Logging and Alerting Failures)

- An audit trail: Structr's changelog (on, as now) and each booking's Process naming who; sign-ins and
  failed sign-ins logged with the address; admin actions logged apart.
- Alerts on many failed sign-ins, rate-limit refusals and errors, sent somewhere a person reads.
- No secrets in logs (checked live for passwords: none), and logs kept for a set time, then deleted.

### 4.9 Errors (A10 Mishandling of Exceptional Conditions)

- A failed request says what to do in plain words and logs the detail (finding 9); it fails closed, as a
  booking does today (nothing of it is kept).

### 4.10 Privacy and the law

- Collect only what planning needs; make each household's data exportable and deletable by its members,
  with what is deleted from backups and when.
- A privacy policy saying what is kept, why, for how long, and who else sees it (the host; Open Food Facts
  sees a barcode looked up, and the address it came from).
- A plan for a breach: who decides, who is told, and how fast, as the law of each place users live requires.
- An agreement with the hosting provider as a processor of personal data; no third-party analytics or
  trackers on the pages.

### 4.11 Before launch

- `security.txt` and an address for reporting a vulnerability.
- An external review aimed at security (the to-do item "Prepare for a third-party review"), with this file
  as its starting list, and a penetration test of the hosted instance.

## 5. In what order

1. **If a phone that browses the web signs in** (it does): finding 1. Its code is in `74c8c2d`.
2. **Before anyone outside the household has an account:** findings 2 to 5 and 9, sections 4.1 and 4.2,
   and the admin interface off the network (4.3).
3. **Before hosting:** the rest of section 4, then the external review (4.11).

## 6. Sources

- OWASP Top 10:2025, <https://owasp.org/Top10/2025/>
- OWASP Application Security Verification Standard 5.0, <https://owasp.org/www-project-application-security-verification-standard/>
- OWASP Cross-Site Request Forgery Prevention Cheat Sheet, <https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html>
- OWASP Docker Security Cheat Sheet, <https://cheatsheetseries.owasp.org/cheatsheets/Docker_Security_Cheat_Sheet.html>
- OWASP Password Storage Cheat Sheet, <https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html>
- web.dev, "Protect your resources from web attacks with Fetch Metadata", <https://web.dev/articles/fetch-metadata>
- MDN, "Cross-site request forgery (CSRF)", <https://developer.mozilla.org/en-US/docs/Web/Security/Attacks/CSRF>
- NIST SP 800-63B-4, Digital Identity Guidelines: Authentication, <https://pages.nist.gov/800-63-4/sp800-63b.html>
- Mozilla SSL Configuration Generator, <https://ssl-config.mozilla.org/>
- AWS Well-Architected SaaS Lens, tenant isolation, <https://wa.aws.amazon.com/saas.question.SEC_2.en.html>
- Neo4j Operations Manual, authentication and authorization (roles are Enterprise Edition only), <https://neo4j.com/docs/operations-manual/current/authentication-authorization/>
- FTC, Health Breach Notification Rule (amended 2024), <https://www.federalregister.gov/documents/2024/05/30/2024-10855/health-breach-notification-rule>
- Regulation (EU) 2016/679 (GDPR), Article 9, <https://eur-lex.europa.eu/eli/reg/2016/679/oj>
- Structr 7.1.0's settings and servlets, read from its image (`docs/structr-reference.md` §3 and §11)
