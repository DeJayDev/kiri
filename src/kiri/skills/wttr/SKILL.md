---
name: wttr
description: Get weather with curl against wttr.in. Read this before fetching weather -- it has the exact command to run.
---

# wttr.in

Weather over plain curl, no API key.

For any weather question, run this:

    curl -s 'wttr.in/<loc>?format=%l:+%C,+%t+(feels+%f),+wind+%w,+humidity+%h\n'

    London: Sunny, +67°F (feels +67°F), wind 9mph, humidity 73%

Keep the URL single-quoted exactly as written. Omit `<loc>` to use the
server's IP-based guess of your location. Spaces in names become `+`
(`Salt+Lake+City`); airport codes (`sfo`), landmarks (`Eiffel+Tower`), and
domains (`@github.com`) also work. Units follow the requester's IP; append
`&u` (USCS), `&m` (metric), or `&M` (metric, wind in m/s) to override.

Only when the question needs data that line lacks -- a forecast, hourly
detail, sunrise/sunset -- fetch the JSON:

    curl -s 'wttr.in/<loc>?format=j1'

The blob is tens of kilobytes; pipe it through jq and keep only the fields
the question needs. Three days of 3-hourly forecast live under `.weather[]`,
current conditions under `.current_condition[0]`, astronomy under
`.weather[].astronomy[0]`.

If wttr.in times out or errors, retry against wttr.is -- same backend,
drop-in equivalent.
