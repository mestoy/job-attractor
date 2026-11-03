"""The praise rules the Build screen gives the model when it phrases a praise line (BUG-658).

These eight sentences are the outreach method's own wording on how to praise, not anyone's private
facts, so the kit ships them. Three readers share this one text:
  - scripts/build_app_feed.py emits PRAISE_RULES as feed["writing_method"]["praise_rules"];
  - app/design/phases/build.py reads that key and puts it in the praise prompt and the praise panel;
  - an install that keeps its own copy (a marked block in a skill document) has a test that pins
    its block equal to this list.
Plain words, American spelling, no dashes. One sentence each.
"""

PRAISE_RULES = [
    "Praise what changed because of it, in their domain's terms, never the duty. If the sentence would read the same at any company, it is a duty, so rewrite it.",
    "Open on them with \"I really like\", then say in one clause why it mattered in their domain. Use \"really\" only in that opening.",
    "Pair it with one accomplishment of your own only when your record gives one that fits. When it gives none, say nothing about yourself.",
    "It must pass the one-of-a-kind test: if it could be sent to anyone else, make it more specific to this person.",
    "Use your own words. Do not repeat the source's phrases; a light paraphrase is the most you take from it.",
    "For a boss who is not a founder, praise the design or product choice, never a company outcome as their personal doing. For a founder, the company's work is theirs.",
    "The boss comes first, and the organization is a valid subject when the source is about the organization. Say which one you are praising.",
    "Never imply you read something they wrote when the source is a record. Say what kind of source it is.",
]

# The fill when a page has no rules at all (an empty list): one honest line instead of silence.
PRAISE_RULES_NEUTRAL = "Praise one specific thing they did and say why it mattered to them."
