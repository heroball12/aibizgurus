# MaryJain’s cannabis education reference

MaryJain answers educational cannabis questions in voice and text. Her source of maintained facts is `core/data/cannabis_knowledge.json`: 26 topics, 22 sources, checked 2026-09-16. The public, searchable version is `/demo/cannabis/knowledge/`, linked from her text and call interfaces. It separates established chemistry, clinical evidence, preliminary research and unknowns.

## Scope

- Plant chemistry, the endocannabinoid system, major/minor cannabinoids and terpene research.
- Strain naming, chemotypes, genetic/environmental variation and five named examples from a published chemical dataset.
- Specific cannabinoid medicine approvals; pain, cancer-related symptoms, MS spasticity, sleep, bowel disease, glaucoma, anxiety and PTSD evidence.
- CBD interactions, delayed edible effects, dependence, accidental exposure, pregnancy, driving, lung/heart effects and novel cannabinoids.
- COAs, measurement uncertainty and the roles of cultivation, manufacturing, testing, distribution and retail.

This is not an exhaustive strain registry. Keywords for common names are routing hints, not verified genetic records. Only the five examples in `named-strain-research` have dataset-specific chemistry notes; none has an assigned medicinal indication. Unknown names must not acquire invented parentage, cannabinoid percentages, terpene profiles or benefits. No recommendation engine, shopping integration, purchase/delivery flow, clinical dosing, current-law lookup or dangerous production instructions are included.

## How it reaches the assistant

`core/cannabis_knowledge.py` loads the repository JSON. Every topic's compact `voice` note is included in the shared MaryJain persona, so the live character has all 26 topic summaries on every call. The persona is 8,084 characters and leaves room for the maximum visitor introduction context under Runway's 10,000-character limit. The current reference is not live web retrieval or model training.

Text chat also selects up to three relevant full summaries using normalized, word-bounded keyword matches, favoring specific phrases. The existing AI gateway receives those notes with source URLs and only role/content history. A small set of explicit follow-up phrases can reuse the preceding question's topic. This deterministic selector is not semantic retrieval and does not guarantee coverage of every paraphrase.

When the optional text AI is unavailable, the clearly labelled reference preview returns up to two matching notes, useful medical-education boundaries where relevant, or an explicit unknown answer. It no longer rejects ordinary questions just because they contain “strain,” “CBD,” “pain” or “medical.” It does not manufacture answers from uncited model memory.

Related-reading links use repository topic IDs, validated against the selected employee's public topic index. They link to source-bearing reference cards; they are not a claim that a model-generated reply was independently fact-checked. IDs remain with the bounded session history but are stripped before history is sent to the model. Other employees receive no cannabis reference context.

## Sources and editorial maintenance

The JSON records exact URLs and source names for each note. Sources include FDA, NIH/NCCIH, NCI, the AHRQ 2025 pain review, CDC, the VA's explanation of the 2023 PTSD guideline, NIST, California DCC, and the original Smith 2022 and Spindle 2024 research papers. Dates describe this reference check, not the publication date of every linked source. The website's educational summaries are not a clinician-reviewed treatment guide.

For updates:

1. Open and assess the original source; record which formulation, population, outcome and evidence type it actually supports. Prefer regulators, public-health institutions and original research. Do not use retailer effect charts as clinical evidence.
2. Update both `summary` and `voice`, preserving uncertainty and relevant limitations. Keep short original paraphrases rather than copied articles. Check affected source dates and update `reviewed_on` after completing the review.
3. For a proposed named-strain entry, distinguish a provenance claim, chemical measurement and clinical effect. A breeder name alone cannot establish a uniform batch profile; chemical observational data cannot establish a medicinal indication.
4. Run the knowledge tests, including the maximum handoff prompt limit. Keep detailed expansion in text reference notes and the public library if the voice prompt would exceed the provider limit.
5. Run `python manage.py sync_demo_characters --industry cannabis`, then commit the public manifest and deploy the website changes through the normal Git workflow. Updating that existing avatar changes remote defaults immediately; old website code may still override them until deployed.

Revisit sources when relevant evidence or regulation changes. No background updater is installed, and neither UI nor character should claim that facts or laws are checked live.

## Verification limits

Automated checks cover source integrity, prompt capacity with maximum visitor context, relevant topic matching, unknown strains, contextual follow-ups, general education versus personal treatment, urgent exposure guidance, saved related-reading links, model message shape, employee isolation and public library search. The text AI gateway is mocked in tests; local reference previews use no OpenAI key. A provider-ready avatar or session does not by itself verify the accuracy of a real spoken answer.

Verification on 2026-09-16: all 136 Django tests and 35 audio/interface Node tests passed, along with JavaScript syntax, migration drift, whitespace and production static collection checks. Desktop browser checks confirmed the sourced pain-research preview, related-reading links and Blue Dream library search. The existing Runway avatar's persona and greeting matched the local configuration. A temporary personalized session reached READY in 7.56 seconds and was closed without joining a visitor. A complete spoken conversation and mobile-device presentation were not verified in this pass.
