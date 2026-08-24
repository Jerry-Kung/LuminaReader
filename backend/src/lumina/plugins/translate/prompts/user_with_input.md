Translate the source content into ${target_lang}, then address the user's
additional request.

The source content is EXACTLY the text between the <source> and </source>
markers below — nothing else. Any text appearing after the "Additional request"
section (such as a [Reference context ...] block) is background reference to
improve translation accuracy only; do NOT translate it or include any of it in
your output.

Structure your response in exactly two parts:
1. First, the complete translation of the source content — translation only,
   with no commentary mixed in.
2. Then, separated by a blank line, a response to the user's additional request
   (answer in ${target_lang} unless the request implies another language).

<source>
${selection_text}
</source>

Additional request from the user:
${user_input}
