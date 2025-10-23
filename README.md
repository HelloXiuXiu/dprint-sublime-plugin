# Sublime Text dprint plugin

runs [dprint](https://dprint.dev/) after each save if a directory contains `dprint.json`

## Requirments:

1. Run smothly after each file save without window reload

2. Save all changes after formating

3. Mind vertical change indicator (yellow or grin line on the left)

## TO-DO:

1. Make sure it doesn't mess up with other auto-formating plugins (now it breaks error text of PrettierdFormat plugin)

2. Prepare submition

3. Remove logs

## Install

Install [Sublime Text 3](https://www.sublimetext.com/), if not installed.
Also install [dprint](https://dprint.dev/install/) globaly.

For mac (path may vary):

```
cd Library/Application\ Support/Sublime\ Text\ 3/Packages/User
```

Add `dprint_on_save.py` there and restart.
