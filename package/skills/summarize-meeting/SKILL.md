---
name: summarize-meeting
description: Use when the user pastes raw meeting notes or a transcript and wants the decisions, action items and open questions. Do not use for agendas or for notes that are not from a meeting.
---

# Summarize a meeting

## Steps

1. Read the whole text once. Note who spoke if the text names speakers.
2. List every decision: a sentence in which the group agreed or someone with authority chose. A proposal nobody answered is not a decision.
3. List every action item: a task someone took on or was given. Attach the owner and the due date only when the text states them; otherwise write `not stated`.
4. List the open questions: things raised and left unanswered.
5. Return the three sections in the order given in the standing instructions. Check each action item against the text once more before answering.

## Example

Input:

```
Sam: we ship the beta on the 14th. Priya will write the release notes by the 10th.
Lee asked whether the pricing page needs legal review. Nobody knew.
```

Output:

```
## Decisions
- Ship the beta on the 14th.

## Action items
- Priya: write the release notes (due the 10th)

## Open questions
- Does the pricing page need legal review?
```

For the exact format of each section see [the format reference](references/format.md).
