# Files the pages load

`tools/install_pages.py` puts every `*.js` here in Structr's folder `/mealplanner/`, served at
`/mealplanner/<name>` to signed-in users only, and replaces them whole on each run.

| File | What | Source |
|---|---|---|
| `mealplanner-camera.js` | the pantry page's "Scan with camera" (`docs/pantry.md`, "Scanning with a phone's camera") | this project |
| `mealplanner-lookup.js` | the pantry page's look-up of an unknown barcode on Open Food Facts (`docs/pantry.md`, "Looking up an unknown barcode") | this project |
| `zxing-library-0.23.0.min.js` | the ZXing barcode reader, loaded by the camera only where the browser has no reader of its own (Safari, a desktop) | `@zxing/library` 0.23.0 from npm, `umd/index.min.js`, unchanged; sha256 `3ede94153fb0c5b67a12d7adff6decd827c2b22714fdc6faecf27a8f20937ea6`. Apache License 2.0, in `zxing-LICENSE.txt` |

It is kept here, not fetched from a CDN, so scanning works on a home network without the internet
and tells no one else what is scanned. (The look-up is the one file that calls out: from the browser,
to Open Food Facts, with the barcode of a product not yet known here, and nothing else.) To change its version, replace the file, change `READER_FILE`
in `pages/lib/55_products.js`, and run the offline tests (`tests/test_pantry_camera.py` reads a barcode
with it in Chromium).
