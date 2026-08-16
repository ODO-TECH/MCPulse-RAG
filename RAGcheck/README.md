# RAGcheck QQ Bot Variant

This directory contains the QQ bot delivery variant of `RAGcheck`.

It uses the same health-check logic as the email variant in `RAGcheck/`, but sends reports to a QQ bot webhook instead of SMTP.

Before publishing or deploying:

- copy `.env.example` to `.env`
- fill in your QQ bot webhook and optional token
- keep `.env` out of version control
