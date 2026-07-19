# Feature Specification: News Rotation Proxy

**Status:** Complete  
**Feature:** 007-news-rotation-proxy

## Purpose

Produce a reproducible, read-only comparison of memory-stock and Magnificent-7
news attention, sentiment, and price/volume behaviour. It is a rotation proxy,
not evidence of real-time institutional trading.

## Requirements

1. Read an EODHD token only from a named environment variable; never print or
   persist it.
2. Archive raw EODHD sentiment responses by ticker and request period.
3. Aggregate daily article count and normalised sentiment for fixed, explicit
   memory and Mag-7 baskets, then join local validated daily price data.
4. Write dated CSV and JSON evidence including basket definitions and an
   explicit proxy limitation.
5. Avoid same-day look-ahead: reported forward returns begin after each
   completed signal date.
6. Produce a cached EODHD sector-ETF report that ranks 21-session adjusted-price
   performance versus SPY and reports final-day relative volume. It must state
   that price/volume leadership is not proof of institutional flows.
7. On request, produce a daily historical sector-rotation report and a daily
   semiconductor-versus-SPY summary using only completed-session data.
8. Produce current-ETF-constituent breadth across all US-listed SMH, SOXX, and
   XSD holdings. The output must explicitly distinguish a current holdings
   snapshot from point-in-time historical holdings.
9. Join the completed-session semiconductor ETF regime with the existing
   Memory price/volume/news-sentiment proxy without requiring Fundamentals data.

## Acceptance scenarios

- Missing token fails before any network request and does not expose a secret.
- A result records ticker-level observation dates rather than claiming that a
  current response represents current institutional ownership.
- Re-running a cached request is deterministic unless `--refresh` is given.
