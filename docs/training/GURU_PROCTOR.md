# Guru as trainer and proctor

Guru explains, demonstrates, challenges and helps an employee retry. The server records evidence; the manager certifies. Guru does not impersonate the human AI Specialist who conducts client assessments.

## Modes

| Mode | Current behavior |
| --- | --- |
| Teach | Explain the current lesson's supplied summary, field guide and approved sales policy |
| Quiz | Ask conversational practice questions; official knowledge checks stay in the server-graded Academy form |
| Role-play | Simulate a fictional prospect, including appropriate exits and disqualification |
| Coach | Debrief actual supplied answers and reviewed evidence |
| Retest | Focus on a missed skill and invite a second attempt |
| Recommend | Suggest a suitable assigned lesson; cannot silently assign training |

The live persona includes the employee's assigned tracks/phases/certification, published-module progress, current lesson summary and field guide, recent quiz performance, recent practice and bounded skill feedback. The current lesson takes priority when the provider's context limit requires older activity to be omitted; the serialized context is never cut midway through a record. It is a compact snapshot, not unlimited memory of the entire curriculum. Start a new session to load newly saved results. It does not receive other employees' records, raw CRM leads or answer keys. A private live-session identifier cannot be reused by another employee.

## Written role-play and feedback

The saved practice page records the fictional dialogue, learner's handoff and linked retry. With the existing platform text-AI credential configured, Guru generates responsive prospect replies and advisory feedback after submission. Scores are 1–10 only for applicable rubric skills with actual learner/handoff quotes. The server rejects invented quotes, unknown skills, invalid numbers and malformed provider results. Feedback is advisory and separately preserved when a manager reviews the attempt.

Managers see both attempts and the change between reviewed scores, not a permanent employee rating. They review the transcript/handoff, score each skill, identify critical failures and write the next practice focus. Only manager-reviewed evidence can satisfy role-play prerequisites.

**TECHNICAL LIMITATION:** The platform text-AI key is absent in the current local configuration. The page therefore explicitly identifies scripted guided rehearsal. It does not manufacture an automatic score. Configured production credentials may differ; no Render secret was inspected or changed. Provider failures also fall back to guided replies while preserving the user's submission. A failed advisory assessment leaves the saved practice waiting for manager review.

## Live sessions

Live Guru uses the existing Runway Characters integration and its Type/Speak interface, voice-reactive helmet artwork, mic turn-taking and typing notifications. Calls are limited by the existing configured maximum (five minutes); they are separate from the 15-minute recorded lesson player. No new live calls were started during implementation testing.

Live coaching has no external-action tools and cannot book, send outreach, change CRM, assign training, write completion or certify. Its coaching is not automatically saved as a scored role-play. Employees use saved written practice or a manager-observed mock call for formal evidence. There is no stored microphone audio, voice-emotion inference or real-call analysis in Phase 1. The live interface's existing Runway terms apply to provider processing.

## Feedback quality

Reference what the employee said. Identify what worked, what was missed and the question that should come next. Then ask for a retry. Example: “You offered a receptionist after they said phones were fine. Ask how quotes get followed up.” Do not fabricate talk time or say “great job” regardless of performance. For unknown policy, ask management rather than inventing the rule.

**FUTURE FEATURE:** adaptive skill plans, campaign-aware drills, daily warmups and audio-based observations with explicit recording/retention approval.
