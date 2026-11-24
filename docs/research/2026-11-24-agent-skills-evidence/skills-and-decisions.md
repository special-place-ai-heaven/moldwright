# Skills and architecture decisions: evidence digest

## What do the two articles actually say?

### Takeaway

Both complete article bodies were recovered through Crawl4AI from dated Internet Archive captures. The supplied www URLs returned 404, and non-www redirected to those 404 pages. The captures establish what the articles said in those versions, not their current contents.

### Cited findings

- **Skills article:** [January 21, 2026 capture](https://web.archive.org/web/20260121004024id_/https://www.outcomeops.ai/blogs/anthropic-says-build-skills-not-agents). Coverage: introduction and talk link (claim that one universal agent replaces custom agents); Skills Revolution (folders, instructions and scripts); Enterprise Reality (adoption claims); We Call Them ADRs and Spring PetClinic (three-record comparison); Perfect Alignment (vector search versus dynamic loading); Why This Matters and Validation (analogy and timeline); From Theory to Production (price, ROI, air-gap and compliance claims); What This Means and CTA (product pitch).
- **ADR article:** [February 12, 2026 capture](https://web.archive.org/web/20260212130045id_/https://www.outcomeops.ai/blogs/what-is-an-adr-and-why-theyre-critical-for-ai-powered-development). Coverage: Problem and What is an ADR (missing rationale, one decision); Examples (database, versioning, deprecation); Best Practices (location, when to write, statuses); Mistakes (timing, rationale, length, changes, small decisions); No ADRs (index documentation, generate code maps, query for a reviewed draft); Why ADRs Matter (PetClinic claim); Getting Started and Enterprise Implementation (template and product pitch).
- **Discard as evidence of general superiority:** OutcomeOps claims $2.24 per generated PR, 100–200× ROI, Fortune 500 deployments, zero IP leakage and automatic compliance, but the skills article does not provide a methodology or supporting primary data for those numbers or guarantees. Its adoption counts and “one universal agent” framing are also vendor reporting, not an independently verified result. [Skills article, Enterprise Reality and From Theory to Production](https://web.archive.org/web/20260121004024id_/https://www.outcomeops.ai/blogs/anthropic-says-build-skills-not-agents).
- **Do not equate an ADR to a skill:** an ADR records one significant decision, its context and consequences; a skill is a procedural package that can include executable scripts and optional references. An ADR can be useful context inside a skill, but the formats and jobs are not interchangeable. [Nygard, Decision](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions); [Agent Skills specification, directory structure and body](https://agentskills.io/specification#directory-structure).

### Inferences

- Distinguish documenting decisions from teaching a repeatable procedure: this is our analysis, not the skills article's position, which equates ADRs with skills. Discard the product promotion and the universal-agent conclusion until tested against the actual work.

### Gaps

- The embedded summit talk was not read or viewed; its precise quotes, adoption counts and interpretation remain unverified. Anthropic's own engineering article below is a related primary source, not a transcript of that talk.
- A later June ADR capture and other attempted snapshots rendered a 404; no claim is made about later changes. The article's final CTA and footer were reached in the recovered February body.

## What primary evidence and practical ideas are relevant?

### Takeaway

The best-supported practical proposal is to test a narrowly scoped skill against representative tasks, with and without it, while recording significant decisions separately with their rationale and status. Neither the skill format nor the ADR format by itself proves a quality improvement.

### Cited findings

- Anthropic describes progressive disclosure: startup metadata, a loaded `SKILL.md`, and referenced files loaded as needed; it recommends observing representative failures first, iterating based on actual use, and inspecting third-party skills and scripts. This is the vendor's design guidance, not a controlled effectiveness measurement. [Anthropic, Anatomy and Developing and evaluating skills](https://www.anthropic.com/research/equipping-agents-for-the-real-world-with-agent-skills#developing-and-evaluating-skills).
- The specification requires a `SKILL.md` with name and description; scripts and references are optional, and `allowed-tools` is experimental with support varying by client. Its approximately 100-token metadata and under-5,000-token body figures are guidance, not a measured guarantee for a particular runtime. [Agent Skills specification, frontmatter and progressive disclosure](https://agentskills.io/specification#progressive-disclosure).
- Nygard's 2011 primary account recommends a short record with title, context, decision, status and positive and negative consequences; retain superseded records and link replacements. His early experience involved six to ten developers rotating through a few projects and reporting appreciation for the context; it was not a controlled study or a quantified AI result. [Nygard, Decision and Experience Report](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions).
- OutcomeOps presents selected PetClinic files and describes three applicable ADRs. The complete [first tree](https://api.github.com/repos/bcarpio/spring-petclinic/git/trees/8a95e0c?recursive=1) contains controller, DTO and service files in two package roots; the complete [second tree](https://api.github.com/repos/bcarpio/spring-petclinic/git/trees/c3b4e8d?recursive=1) contains the two shown `stats` source files, two `stats` tests and five ADRs (001–005). Both responses report `truncated: false`; the article's illustrations are not complete trees. The [compare API](https://api.github.com/repos/bcarpio/spring-petclinic/compare/8a95e0c...c3b4e8d) reports 26 commits and 12 changed files in a three-dot merge-base comparison, not a direct tip-to-tip diff. Tree contents cannot establish which ADRs were retrieved or caused the differences; this vendor demonstration does not establish a repeatable average or controlled conditions.

### Inferences

- Candidate procedure, not a finding about the existing repository: select recurring work with observed failures; collect representative tasks including cases where the skill should not trigger; compare the same model and environment with and without the skill; record task success, incorrect triggering, time and token usage; inspect failures before adopting. Include a human review of any generated ADR and distinguish observed code behavior from historical intent that the code cannot prove.
- Link an accepted decision's current record and replacement from relevant procedural guidance; retrieve only applicable material. Check current repository practices first rather than introduce a parallel decision store.
- A changed file tree alone does not show correctness, maintainability, causation or improvement; measure these separately and retain the actual outputs and conditions.

### Gaps

- No independent controlled study establishing the articles' AI productivity, ROI, or general reliability claims was obtained. No Moldwright-specific baseline, skill experiment, or implementation check was performed in this research.
