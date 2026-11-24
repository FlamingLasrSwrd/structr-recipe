"""The pantry page's camera (pages/files/mealplanner-camera.js; docs/pantry.md, "Scanning with a phone's
camera"), in a real browser: Chromium through Playwright, where node can load it, with a barcode drawn
here standing in for the camera. The page is pages/pantry.js printed over tests/test_pantry_scan.py's
stand-in graph, with the two files installed, and served to the browser at a made-up address.

The barcode is the EAN-13 4006381333931 (its check digit worked in tests/test_products.py), drawn from
the EAN-13 tables (GS1 General Specifications 5.2.1.2): bars of 4 pixels a module, on white.

  the camera: Chromium's own reader is not on Linux, so the ZXing reader is loaded and reads the frames;
              what it reads is sent through the barcode box, as typed
  a browser's own reader (a stand-in BarcodeDetector) is used where it reads product barcodes, and
              ZXing is then never loaded; a code with a wrong check digit is never sent
  over http:// the browser gives no camera, so a photo is read instead
"""

import json
import os
import pathlib
import shutil
import struct
import subprocess
import tempfile
import unittest
import zlib

from tests.test_pantry_buy_unit import page_code
from tests.test_pantry_scan import GRAPH
from tests.test_signed_out import javascript

ROOT = pathlib.Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
CODE = "4006381333931"
L = ["0001101", "0011001", "0010011", "0111101", "0100011", "0110001", "0101111", "0111011", "0110111", "0001011"]
PARITY = ["LLLLLL", "LLGLGG", "LLGGLG", "LLGGGL", "LGLLGG", "LGGLLG", "LGGGLL", "LGLGLG", "LGLGGL", "LGGLGL"]


def ean13_modules(code: str) -> str:
    """The 95 modules of an EAN-13, 1 for a bar."""
    right = lambda d: "".join("1" if b == "0" else "0" for b in L[int(d)])
    left = "".join(L[int(d)] if p == "L" else right(d)[::-1] for d, p in zip(code[1:7], PARITY[int(code[0])]))
    return "101" + left + "01010" + "".join(right(d) for d in code[7:]) + "101"


def picture(code: str, width=640, height=480, module=4) -> list[bytes]:
    """Grey rows: the barcode in the middle of a white picture."""
    bars = ean13_modules(code)
    x0, top = (width - len(bars) * module) // 2, height // 4
    row = bytearray([255] * width)
    for i, bit in enumerate(bars):
        if bit == "1":
            row[x0 + i * module: x0 + (i + 1) * module] = bytes(module)
    return [bytes(row) if top <= y < height - top else bytes([255] * width) for y in range(height)]


def png(rows: list[bytes]) -> bytes:
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    header = struct.pack(">IIBBBBB", len(rows[0]), len(rows), 8, 0, 0, 0, 0)       # 8-bit grey
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(b"".join(b"\0" + r for r in rows))) \
        + chunk(b"IEND", b"")


def y4m(rows: list[bytes], frames=10) -> bytes:
    """A video of the picture, for Chromium's stand-in camera (--use-file-for-fake-video-capture)."""
    w, h = len(rows[0]), len(rows)
    frame = b"FRAME\n" + b"".join(rows) + bytes([128]) * (w // 2 * h // 2 * 2)
    return f"YUV4MPEG2 W{w} H{h} F10:1 Ip A1:1 C420jpeg\n".encode() + frame * frames


def pantry_page() -> str:
    graph = GRAPH.replace("REQUEST", "{}") + """
node("File", "mealplanner-camera.js", {path: "/mealplanner/mealplanner-camera.js", checksum: 11});
node("File", "zxing-library-0.23.0.min.js", {path: "/mealplanner/zxing-library-0.23.0.min.js", checksum: 22});"""
    return javascript("var result = (function () {\n" + graph + "\n" + page_code() + "\nreturn $.out; })();")


DRIVER = r"""
const { chromium } = require('playwright');
const [origin, video, photo, page_html, init, action] = JSON.parse(process.argv[process.argv.length - 1]);
const fs = require('fs');
(async () => {
  const browser = await chromium.launch({args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream',
                                               '--use-file-for-fake-video-capture=' + video]});
  const context = await browser.newContext();
  await context.grantPermissions(['camera'], {origin: origin});
  const page = await context.newPage();
  const asked = [], scans = [];
  await page.route(origin + '/**', (route) => {
    const url = new URL(route.request().url());
    asked.push(url.pathname);
    if (url.pathname === '/structr/html/pantry' && url.searchParams.has('scan')) {
      scans.push(url.searchParams.get('scan'));
      return route.fulfill({contentType: 'text/html', body: '<p>scanned</p>'});
    }
    if (url.pathname === '/structr/html/pantry') return route.fulfill({contentType: 'text/html', body: '<!doctype html><html><head></head><body>' + page_html + '</body></html>'});
    if (url.pathname.startsWith('/mealplanner/')) return route.fulfill({contentType: 'text/javascript', body: fs.readFileSync(process.env.FILES + url.pathname.slice(13))});
    return route.fulfill({status: 404, body: ''});
  });
  if (init) await page.addInitScript(init);
  await page.goto(origin + '/structr/html/pantry');
  const out = {};
  out.buttonShown = await page.isVisible('button.camera');
  await page.click('button.camera');
  if (action === 'photo') {
    await page.waitForSelector('label.camera-photo:not([hidden])', {timeout: 5000});
    out.note = await page.textContent('.camera-note');
    await page.setInputFiles('label.camera-photo input', photo);
  }
  try { await page.waitForURL(/scan=/, {timeout: action === 'never' ? 2500 : 20000}); } catch (e) { out.waited = true; }
  out.scans = scans;
  out.readerLoaded = asked.some((p) => p.indexOf('zxing') >= 0);
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


def browser_can_run() -> bool:
    if not NODE:
        return False
    done = subprocess.run([NODE, "-e", "require('playwright')"], capture_output=True, cwd=tempfile.gettempdir())
    return done.returncode == 0


STAND_IN_READER = """
window.BarcodeDetector = class {
  static getSupportedFormats() { return Promise.resolve(["qr_code", "ean_13", "upc_a"]); }
  constructor(options) { window.__formats = options.formats; }
  detect() { return Promise.resolve([{rawValue: "%s"}]); }
};"""


@unittest.skipUnless(browser_can_run(), "needs node with Playwright and its Chromium")
class TheCamera(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        rows = picture(CODE)
        cls.video, cls.photo = pathlib.Path(cls.dir.name, "camera.y4m"), pathlib.Path(cls.dir.name, "photo.png")
        cls.video.write_bytes(y4m(rows))
        cls.photo.write_bytes(png(rows))
        cls.html = pantry_page()

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def drive(self, origin="https://pantry.test", init=None, action="camera") -> dict:
        args = json.dumps([origin, str(self.video), str(self.photo), self.html, init, action])
        done = subprocess.run([NODE, "-e", DRIVER, args], capture_output=True, text=True, timeout=120, cwd=tempfile.gettempdir(),
                              env={**os.environ, "FILES": str(ROOT / "pages" / "files") + "/"})
        if done.returncode:
            raise AssertionError(done.stderr)
        return json.loads(done.stdout.strip().splitlines()[-1])

    def test_the_drawn_barcode_is_an_ean_13(self):
        self.assertEqual(len(ean13_modules(CODE)), 95)
        self.assertEqual(ean13_modules("4006381333931")[:10], "1010001101")    # start, then 0 by L: 0001101

    def test_the_camera_reads_a_barcode_with_zxing_and_sends_it_through_the_box(self):
        got = self.drive()
        self.assertTrue(got["buttonShown"])
        self.assertEqual(got["scans"], [CODE])
        self.assertTrue(got["readerLoaded"])

    def test_a_browsers_own_reader_is_used_and_zxing_is_never_loaded(self):
        got = self.drive(init=STAND_IN_READER % "036000291452")
        self.assertEqual(got["scans"], ["036000291452"])
        self.assertFalse(got["readerLoaded"])

    def test_a_code_with_a_wrong_check_digit_is_never_sent(self):
        got = self.drive(init=STAND_IN_READER % "036000291453", action="never")
        self.assertEqual(got["scans"], [])

    def test_without_https_a_photo_is_read_instead(self):
        got = self.drive(origin="http://pantry.test", action="photo")
        self.assertIn("https://", got["note"])
        self.assertEqual(got["scans"], [CODE])


if __name__ == "__main__":
    unittest.main()
