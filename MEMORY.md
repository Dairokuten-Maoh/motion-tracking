# Personal memory

Jarvis keeps saved notes and tasks in `personal_memories` in the existing private
`jarvis-data/archive.sqlite3` database. They persist across phone/web sessions and
restarts until explicitly forgotten. No cloud model or extra subscription is used.

Examples in normal conversation:

- "Remember that I prefer oolong tea."
- "What tea do I prefer?"
- "That's wrong, I prefer black tea."
- "Remember to call the bicycle shop."
- "Mark it finished."
- "List my saved tasks."
- "Forget that." Or identify the note by its ID or a distinctive phrase.

Saving requires an explicit request. Ordinary personal disclosures and ambient
recordings are not automatically converted into personal facts. Saved text is an
exact excerpt of the current request, limited to 500 characters. A saved task is
a checklist item: saving or completing it never creates a calendar reminder or
executes the task. An ambiguous target asks for clarification without changing it.
"That" uses only the latest reply's focused memory in the current session.

Relevant saved notes can inform ordinary chat. Retrieval uses English keyword
overlap and Chinese character pairs, at most six notes and 2,000 serialized
characters. This is lexical retrieval, not semantic embedding search; paraphrases
without shared words can miss a note. Listing returns up to six recent matches,
not an exhaustive inventory. Task lists include open/done status.

The action planner receives no retrieved memory content. After routing a request
to chat, a separate text-only call may use relevant notes; it has no action/tool
dispatcher. This adds one local model call only when relevant notes are found.
Memory-related dialogue records are reduced to operation/focus metadata for the
action planner; memory-assisted replies are omitted from its stored context.
The experimental OpenJarvis planner has not been evaluated for memory routing.

Corrections replace saved text. Forgetting deletes the saved row. Both also clear
affected dialogue context (retaining unrelated turns outside the active session) so old values cannot persist through conversational
follow-ups. They do **not** erase original recordings, transcripts, diary entries,
or backups; explicitly asking about the recording archive can still recover
recorded words. This is logical deletion, not secure erasure of SQLite disk pages.

"What did I discuss yesterday?" continues to use existing dated transcript
retrieval and exact source citations. Diary summaries are available in the timeline;
they are not promoted into user-owned tasks or personal memories.
