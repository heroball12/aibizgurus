# Manager guide

Owner/admin roles use **Sales → Workspace → Email copilot settings**. Ordinary employees cannot access these settings. Managers can enable the generator, change defaults, configure approved messaging and forbidden phrases, manage services and conversation types, and add employee profiles/signatures and scheduling URLs.

For Erykha, enter the approved name, business email/phone and professional background in her profile. Do not add personal/private employee information. A professional automotive background can then be referenced when relevant; it is not forced into every email.

Quality review shows recent drafts, selected services/types, feedback, generation/regeneration/saved/manually-sent counts and workflow event totals. These are quality/workflow signals, not simplistic employee performance scores. Generating, editing or saving drafts does not increment call metrics. Marking sent creates one email activity; repeated requests do not duplicate it. Delivery, replies and assessment attribution are not measured by copy/paste and are deliberately not fabricated.

Thumbs-up/down and reasons support later human review. Feedback never changes prompts automatically. Core pricing, claim and permission restrictions cannot be disabled in this page.

On deployment, run migrations; defaults are seeded automatically. Retain the existing Render AI key. No new Gmail/SMS credential is needed. Before field rollout, run the live synthetic acceptance evaluation, review actual model output and verify Gmail clipboard behavior on the employees' browsers. No real prospect email needs to be sent during QA.

Email drafting uses `SALES_EMAIL_MODEL` (default `gpt-5-mini`) with the existing platform key. This is separate from `OPENAI_CHAT_MODEL`, so fixing email does not silently change other assistants. GPT-5 Mini requests omit the unsupported temperature parameter and use minimal reasoning for short drafts. The chosen model must be enabled for that key's OpenAI project.

If generation fails, the workspace distinguishes model/permission configuration, rejected keys, credit/spending limits, daily site allowance, temporary rate limits, connection failures and timeouts. Configuration failures say **Administrator action needed** rather than inviting repeated retries. In Django administration, filter **Assistant AI → Usage records** to `sales_email`; the error code and `metadata.provider_error` contain safe status/code details. Prompts, keys and raw provider error messages are not logged.

The October 2 production failure was a confirmed HTTP 403 `model_not_found`: the old request used `gpt-4o-mini`, while the existing Render key only listed `gpt-5-mini`. A generic request to the permitted model succeeded from Render. Deploy the model compatibility fix together with the email model selection; changing only the old model setting would still leave an unsupported temperature parameter in the request.
