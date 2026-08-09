# Moderated Session and Interview Guide

## Opening

1. Read `participant-consent.md` and confirm consent.
2. “Tell me about the last time you moved a coding task from one agent to another.”
3. “What did you copy, repeat, or ask the second agent to rediscover?”
4. “How do you currently preserve why an agent-made change exists?”

Do not describe the product thesis before the measured tasks.

## After each handoff condition

Ask before showing source-session truth:

1. “How confident are you that the receiving agent understood the task? One to five.”
2. “How much did you trust the context it received? One to five.”
3. “What information was missing, unnecessary, or suspicious?”
4. “Would you have intervened differently in your own repository?”

Then reveal the original decisions:

5. “Did the supplied context omit or distort anything that would change the implementation?”
6. “Was preparing or reviewing this context worth the time it saved?”

## Provenance scenarios

Show `explain-mockup.md` without describing intended value.

### Code review

“You are reviewing a change that extends this caching layer. What would you do next, and did this output change that?”

### Debugging

“Production data suggests stale personalized feeds. Which evidence here would affect your first debugging step?”

### Onboarding

“A new engineer asks why Redis was selected. What can you answer, and what would you still verify?”

For each scenario record:

- concrete action before and after seeing provenance;
- fields used;
- fields distrusted or missing;
- whether source evidence would need to be opened;
- time to answer the who/why/alternatives/review/merge questions.

## Closing

1. “Rank structured handoff and code provenance by value to you.”
2. “Which one, if either, would make you install a new CLI on a real repository?”
3. “What is the smallest workflow interruption that would make you stop using it?”
4. “What information must never be committed to the repository?”
5. “If this disappeared after six months, what—if anything—would you miss?”

Avoid asking whether the participant “likes” the product. Ask for decisions, tradeoffs, and recent examples.

