---
name: fx
description: Convert currency or get an exchange rate. Read this before doing any currency math -- it has the exact v2 command and the rate is per one unit, so you multiply.
---

# frankfurter (v2)

Exchange rates over plain curl, no key. Rates are the ECB reference set,
updated once a day on weekdays.

    curl -s 'https://api.frankfurter.dev/v2/rates?base=USD&quotes=EUR,GBP'

    [{"date":"2026-07-20","base":"USD","quote":"EUR","rate":0.8738},
     {"date":"2026-07-20","base":"USD","quote":"GBP","rate":0.7430}]

The response is an array of `{date, base, quote, rate}` objects; pull `.rate`
from the entry whose `quote` you want. `quotes` takes a comma-separated list
for several at once. Codes are uppercase ISO 4217.

`rate` is per one unit of `base`. To convert an amount, multiply it yourself:
100 USD is `100 * 0.8738`. v2 removed the old `amount` parameter -- passing it,
or any other unknown parameter, is a hard `422`, not a warning.

Single pair without the array wrapper:

    curl -s 'https://api.frankfurter.dev/v2/rate/USD/EUR'   ->  one {date,base,quote,rate}

Historical is a one-day range on `/v2/rates`, not a path segment -- a date in
the path 422s as an "invalid currency":

    curl -s 'https://api.frankfurter.dev/v2/rates?base=USD&quotes=EUR&from=2025-01-02&to=2025-01-02'

Only ~30 fiat currencies, no crypto and no metals. A request for BTC or gold
422s on the currency code here -- say so and reach for a price API, don't retry
this endpoint.
