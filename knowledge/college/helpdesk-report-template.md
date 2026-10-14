---
title: "{{COLLEGE_NAME}}: how to write a security incident report for the helpdesk"
source_type: college
---

## About this template

Sample guidance written for a course project. It is not an official policy of {{COLLEGE_NAME}}. It describes how a student should summarise a suspicious-message incident for {{HELPDESK}} so that staff can act without asking the same questions again.

## Structure of a good report

A report is most useful when facts, observations and open questions are kept apart:

1. Summary: one or two sentences describing what happened and when.
2. What the student reported doing: received only, opened the link, downloaded or opened a file, entered a password, entered an MFA code or approved a prompt, reused the password elsewhere.
3. What was observed: the sender address, reply-to address, links and their real domains, attachment names, and any warning signs found by checking the message. Each observation should say where it came from.
4. Actions already taken: for example password changed at a given time, sessions signed out, file deleted.
5. Open questions: anything that is not yet known, such as whether the password is used on other accounts or whether anything was installed.

## Tone and accuracy

Write plainly and do not guess. "The link pointed to a domain that is not {{COLLEGE_DOMAIN}}" is more useful than "this was definitely a hacker". If no warning signs were found, say so, but do not claim the message was safe; say how it was verified, if at all.

## Sensitive information

Never include your password, MFA codes or recovery codes in a report. The helpdesk does not need them and will never ask for them.
