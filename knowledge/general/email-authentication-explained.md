---
title: Email headers and authentication (SPF, DKIM, DMARC) explained
source_type: general
source_url: https://www.ncsc.gov.uk/collection/phishing-scams
---

## What email headers are

Every email carries technical information called headers, separate from the text you read. They record who the message claims to be from, where replies will go, which servers handled it, and the results of authentication checks made by the receiving mail server. Most email services hide them by default, behind an option such as "Show original", "View source" or "Message details".

## Sender fields

- From: the address and name shown to you. The display name can be set to anything, so only the address is meaningful.
- Reply-To: where your reply will actually go. If it differs from the From address, especially on a different domain or a free email service, replies go to someone else, which is common in scams.
- Return-Path: the address that receives delivery failures. Legitimate mailing services often use their own domain here, so a mismatch alone is weak evidence, but it is still worth noting.

## SPF, DKIM and DMARC

- SPF checks whether the server that sent the message is allowed to send mail for the domain in the envelope sender.
- DKIM checks a digital signature, showing the message was not altered and was signed by a particular domain.
- DMARC checks that SPF or DKIM passed for the same domain shown in the From address, and tells receivers what to do when they do not.

A "fail" on any of these, especially DMARC, is a strong sign that the message did not really come from the domain it claims. "None" means the check could not be made, often because the domain never set it up.

## What a pass does and does not mean

A pass only proves that the message came from the domain in the From address. It does not prove that the domain belongs to who you think, or that the sender is honest. An attacker who registers a lookalike domain can configure SPF, DKIM and DMARC and pass all three, and a message sent from a hacked real account passes too. Authentication results are evidence about the sending domain, not about the trustworthiness of the message.

## Trusting the results

Authentication results are added by the receiving mail server, normally in the topmost Authentication-Results header. Headers copied and pasted by hand can be edited, and older headers lower down can be forged by the sender, so results are only as reliable as their source.
