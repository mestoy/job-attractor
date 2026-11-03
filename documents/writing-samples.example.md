# Writing samples (example)

This file is the source `scripts/build_app_feed.py`'s `build_voice()` reads for the Build
screen's beat prompts. Copy it to `documents/writing-samples.md` and replace these two
OBVIOUSLY FAKE samples with your own real, actually-sent cold-boss notes.

The parser looks for headers shaped exactly like:

    ## Sample <N> - <anything>, HIS SENT version (<YYYY-MM-DD>, <context>) [type: cold-boss]

or `HIS FINAL` in place of `HIS SENT`. End the header with ONE tag, `[type: <name>]`, from
`cold-boss`, `warm-rung`, `follow-up`, `reply`, `thank-you`, `application-answer`, `narrative`
or `linkedin`; the Build screen draws each kind of note from the matching samples. The header
must also contain "sent" or "final" for the sample to count as a real, sent sample. Sample
numbers may repeat; the app gives each sample its own id from its header line. Everything between one `## Sample` header and the next is the sample's text.

## Sample 1 - cold-boss first contact, HIS SENT version (2026-01-01, Pat Placeholder, Chief Imaginary Officer @ Acme Rocketry, LinkedIn) [type: cold-boss]

Hi Pat Placeholder,

I saw Acme Rocketry's posting for a Head of Make-Believe Products and wanted to reach out
directly. I build the whole cardboard-box prototype myself before I ever ask an engineer
to touch it, and I would love ten minutes to talk about how that habit could help Acme
Rocketry ship its next imaginary launch.

Would you have time this week?

Fictional McTestperson

## Sample 2 - cold-boss first contact, HIS FINAL version (2026-01-15, Sam Sampleton, VP of Make-Believe @ Wonderland Gadgets Co.) [type: cold-boss]

Hi Sam Sampleton,

Wonderland Gadgets Co.'s note about doubling the Rabbit Hole team caught my eye. I spent
the last two years turning a stack of sticky notes into a working teleporter demo on my
own, and I think that same builder habit fits what you are describing.

Open to a quick call?

Fictional McTestperson
