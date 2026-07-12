---
name: on-brand-content
description: "Produce marketing content that stays strictly on-brand: apply a brand's positioning, voice/tone, audience, do's/don'ts, and guardrails from AGENTS.md/SOUL.md before drafting or revising any copy. Use whenever writing social posts, captions, ad copy, emails, or briefs for a specific brand."
metadata:
  hermes:
    tags: [marketing, brand-voice, content, kaizen]
    homepage: internal
---

# On-Brand Content

Guidance for turning a content brief into copy that reads like it was
written by the brand itself, not a generic AI assistant. This is the shared
playbook for Kaizen's Content Creator and Brand Strategist specialists.

## Before writing a single word

1. **Read the brand DNA first.** Every tenant has brand identity in
   `SOUL.md` (agency identity + hard guardrails) and `AGENTS.md` (editable
   brand DNA: positioning, voice/tone, audience, do's/don'ts, channels).
   Never draft content without reading both — a brief alone is not enough
   context.
2. **Identify the channel.** Tone, length, and structure differ by channel
   (e.g. Twitter/X thread vs. LinkedIn post vs. email vs. blog). If the
   brief doesn't specify a channel, default to the brand's primary channel
   from `AGENTS.md`, and say so explicitly in your output.
3. **Check the guardrails before the voice.** Guardrails (e.g. "never
   promise a delivery date we haven't confirmed") are hard constraints —
   violating one is worse than an off-tone draft. Voice/tone notes are
   stylistic; guardrails are non-negotiable.

## Applying voice and tone

- Match the brand's documented tone adjectives literally (e.g. "confident,
  plain-spoken" means short declarative sentences, not hedging language or
  corporate throat-clearing).
- Mirror the brand's documented do's: if "use concrete numbers" is a do,
  every draft should contain at least one concrete, specific detail (a
  number, a named feature, a real outcome) rather than vague superlatives.
- Respect documented don'ts literally (e.g. "don't use exclamation points"
  means zero `!` in the draft, not "use them sparingly").
- When positioning and audience conflict with a generic best-practice
  (e.g. "always add a CTA"), the brand's own documented preferences win.

## Avoiding generic AI-slop copy

Do not ship copy that could be mistaken for a random SaaS company's
content. Concretely avoid, unless the brand's own voice explicitly calls
for it:

- Opening with "In today's fast-paced world..." or similar throat-clearing
- Rhetorical questions as a crutch ("Ever wondered how...?")
- Emoji stacking or exclamation-heavy enthusiasm
- Vague superlatives ("game-changing", "revolutionary", "seamless") without
  a concrete claim backing them up
- A generic three-point listicle structure applied to everything regardless
  of the actual brief

Instead: lead with the single most concrete, specific claim from the brief,
support it with one real detail (a number, a named capability, a specific
outcome), and close with a call to action that matches the brand's
documented voice — not a boilerplate one.

## Research before claims (when Linkup or web tools are available)

If a claim in the brief is unverified (a competitor comparison, a market
stat, a "first/only" claim), verify it with the research tools available
(Linkup search when configured, otherwise `web_search`/`web_extract`)
before stating it as fact. Never fabricate a statistic, quote, or
competitor detail — cite the source inline as a note if the content format
allows it, or flag the unverified claim explicitly in your final response
if it doesn't.

## Before finalizing

Run through this checklist on every draft:

- [ ] Read `SOUL.md` and `AGENTS.md` (or the equivalent brand profile) first
- [ ] No guardrail violated
- [ ] Matches documented voice/tone, not a generic default voice
- [ ] Every do honored, every don't avoided
- [ ] At least one concrete, specific detail (not just adjectives)
- [ ] No unverified factual claims
- [ ] Length and structure fit the target channel
- [ ] Would a person familiar with this brand recognize it as theirs?

If any box can't be checked, say so explicitly in the response rather than
shipping a draft that silently fails the brand's own standards.
