# Guru Sales Academy architecture

Implementation date: 2026-09-25. Phase 1 software is implemented locally. Official training content is not published. Business authority: [owner policy](OWNER_POLICY.md); delivery roadmap: [blueprint](../TRAINING_BLUEPRINT.md).

## Domain and boundaries

The `training` Django app uses the existing database, account roles, CSRF protection, staff navigation and Runway concierge transport. It creates no CRM leads, outreach, bookings or external messages. Database migrations are additive. Existing Render migration commands pick them up; seed content separately with `python manage.py seed_training`.

| Record | Purpose |
| --- | --- |
| Course → Track → Module → ModuleVersion | Catalog, Core/Advanced/industry paths, ordered lessons and immutable approved versions |
| LessonAsset | Private durable video, captions and poster object keys; explicit review flag |
| Quiz → Question → QuizAttempt | Versioned answer keys, server grading, idempotent submissions, explanations and historical passing threshold |
| EmployeeProgress | Resume position, unique watched ranges, active video seconds, server timestamps and retraining cycle |
| RolePlayScenario → RolePlayAttempt | Fictional persona, difficulty, applicable rubric, transcript, handoff, advisory feedback, manager score and linked retries |
| Skill → EmployeeSkill | Observations attached to specific attempts, with source and evidence |
| CertificationAttempt | Employee's enrollment in a track and current training phase |
| TrainingAssignment | Assigned module version, note, deadline and retraining requirement |
| ManagerReview → Certification | Practical evidence, manager decision and requirements snapshot; revocation preserves the award |
| ProctorSession | Scoped owner, current lesson and coaching mode for a short live session |

The general database administrator remains trusted. Model/admin guards prevent routine edits to approved content; these are not tamper-proof audit storage against raw SQL or privileged shell access. Historical records use protected foreign keys and the app supplies no employee deletion controls.

## Request paths

- `/training/`: assigned learning, progress, continue learning, available paths.
- `/training/modules/<id>/`: player, chapters, transcript, knowledge check, job aid and practice.
- `/training/history/`: the employee's own quiz/practice/certification history, including retired versions.
- `/training/practice/<uuid>/`: persisted role-play conversation, handoff, feedback and retry.
- `/training/proctor/<uuid>/`: live Guru coaching, authenticated and scoped to its creator.
- `/training/manage/`: admin/owner assignments, learner records and content preview.
- `/admin/training/`: owner content editing and configurable thresholds; evidence read-only.

Learners require a published version and track assignment to earn evidence. Admin/owner users can preview drafts without earning credit. Only the owner can move publication states or create revisions. POST handlers recheck ownership/role rather than trusting the page that launched them. Practice and quiz mutations are rate limited; duplicate turns/submissions are idempotent. All learning pages use no-cache responses.

## Completion integrity

Five-second heartbeats credit contiguous playback only within a recent server-observed interval. Seeking, repeated sections, invalid times and a single fabricated “ended” event do not earn skipped coverage. This is reasonable progress tracking, not proof of attention or proctored exam security. A learner could emulate time-consistent heartbeats; quizzes, observed practical work and manager approval remain necessary.

Quiz grading never trusts a client score. Required practice must receive manager-reviewed passing evidence; Guru advisory scores cannot satisfy certification directly. See [certification rules](CERTIFICATION.md). Retraining creates a new watch cycle and requires fresh quiz/practice evidence without erasing older attempts.

## Media and AI

Private media supports two backends. With `TRAINING_MEDIA_ROOT`, the app streams authorized files from a persistent disk, supports GET/HEAD and single byte ranges for seeking, and rejects traversal or escaping symlinks. Nothing mounts that folder as public static media. With S3, staff authorization returns a five-minute signed GET redirect; Boto3 uses the standard server credential chain. The full-folder importer verifies all 16 scripts, file hashes and chapter timings, then attaches review assets without publishing. See [Render delivery](RENDER_DELIVERY.md). Local disk playback is checked; production storage and deployed playback acceptance remain required.

Text practice reuses `PlatformAIService`; missing credentials/provider failure use a clearly identified scripted rehearsal and preserve manager review. Live coaching uses the existing Runway key/avatar and shared mic/typing handling. It has no CRM or certification tools. No live practice audio is recorded by this app. Runway still processes the live call. See [Guru Proctor](GURU_PROCTOR.md).

## Development and validation

Install requirements, run migrations, then `python manage.py seed_training`. The command is idempotent and never overwrites an existing reviewed script or publishes a lesson. `seed_training --demo` is DEBUG-only and creates a separate SYNTHETIC draft track with synthetic employee, progress, quiz, practice and manager-review data. Use an isolated development database. Synthetic users receive unusable passwords by default.

Run `python manage.py test training` and the wider Django suite. The first implementation also checks the existing concierge and sheet JavaScript tests, syntax, migrations, and staff pages. Real media delivery and provider-generated coaching need separate integration acceptance when credentials/assets are available.

## Deliberately later

Aggregated analytics, campaign briefs, adaptive assignments, warmups, industry certification prerequisites and real-call analysis belong to later phases. No automatic sales permission change is attached to an Academy award. An advanced-track assignment does not grant quoting or discount authority.
