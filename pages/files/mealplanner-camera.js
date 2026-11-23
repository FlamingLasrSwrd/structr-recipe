// The pantry page's camera (docs/pantry.md, "Scanning with a phone's camera"). Served as a file
// (tools/install_pages.py puts pages/files/ in Structr's folder /mealplanner/), run in the browser.
//
// "Scan with camera" opens the phone's back camera and reads each frame until it finds a product's barcode
// (EAN-13, EAN-8, UPC-A, UPC-E) twice in a row with a right check digit, then puts it in the barcode box
// and sends it, as a scanner that types would. The page does the rest: products.find, Buy filled in,
// or "Add a product". The browser's own BarcodeDetector reads where it has these formats (Chrome on
// Android); elsewhere (Safari, a desktop) the ZXing reader is loaded, from this instance, only then.
// A browser gives a page its camera only over HTTPS (or on localhost); without it, or when the camera is
// refused, a photo taken with the phone's camera app is read instead.
(function () {
  "use strict";
  var button = document.querySelector("form.scan button.camera");
  if (!button) return;
  var box = button.form.querySelector("input[name=scan]");
  var panel = document.getElementById("camera");
  var video = panel.querySelector("video"), note = panel.querySelector(".camera-note");
  var photo = panel.querySelector(".camera-photo"), photoInput = photo.querySelector("input");
  var FORMATS = ["ean_13", "ean_8", "upc_a", "upc_e"];
  var stream = null, running = false, last = null, read = null;

  function say(text) { note.textContent = text; }

  // products.check_digit: from the right, the digits before the last weigh 3, 1, 3, ...
  function rightCheckDigit(code) {
    if (!/^(\d{8}|\d{12,14})$/.test(code)) return false;
    var total = 0, body = code.slice(0, -1);
    for (var i = 0; i < body.length; i++) total += Number(body[body.length - 1 - i]) * (i % 2 === 0 ? 3 : 1);
    if (code.length === 8 && "01".indexOf(code[0]) >= 0) return true;    // a UPC-E: the page checks it spelled out
    return (10 - total % 10) % 10 === Number(code[code.length - 1]);
  }

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = src;
      s.onload = resolve;
      s.onerror = function () { reject(new Error("the barcode reader did not load")); };
      document.head.appendChild(s);
    });
  }

  // ZXing over a canvas: what one image or video frame holds, or null
  function zxingReader() {
    return (window.ZXing ? Promise.resolve() : loadScript(button.getAttribute("data-reader"))).then(function () {
      var Z = window.ZXing, hints = new Map();
      hints.set(Z.DecodeHintType.POSSIBLE_FORMATS, [Z.BarcodeFormat.EAN_13, Z.BarcodeFormat.EAN_8, Z.BarcodeFormat.UPC_A,
                                                     Z.BarcodeFormat.UPC_E]);
      hints.set(Z.DecodeHintType.TRY_HARDER, true);
      var reader = new Z.MultiFormatReader();
      reader.setHints(hints);
      var canvas = document.createElement("canvas"), context = canvas.getContext("2d", {willReadFrequently: true});
      return function (source) {
        var w = source.videoWidth || source.naturalWidth || source.width, h = source.videoHeight || source.naturalHeight || source.height;
        if (!w || !h) return Promise.resolve(null);
        var scale = Math.min(1, 1280 / Math.max(w, h));
        canvas.width = Math.round(w * scale);
        canvas.height = Math.round(h * scale);
        context.drawImage(source, 0, 0, canvas.width, canvas.height);
        try {
          var bitmap = new Z.BinaryBitmap(new Z.HybridBinarizer(new Z.HTMLCanvasElementLuminanceSource(canvas)));
          return Promise.resolve(reader.decodeWithState(bitmap).getText());
        } catch (e) {
          return Promise.resolve(null);       // nothing found in it (ZXing throws NotFoundException)
        } finally {
          reader.reset();
        }
      };
    });
  }

  // The browser's own reader where it reads product barcodes, else ZXing: a function from an image to a
  // promise of the barcode in it, or null
  function reader() {
    if (read) return Promise.resolve(read);
    var own = typeof window.BarcodeDetector === "function" && typeof window.BarcodeDetector.getSupportedFormats === "function"
      ? window.BarcodeDetector.getSupportedFormats().catch(function () { return []; }) : Promise.resolve([]);
    return own.then(function (supported) {
      var formats = FORMATS.filter(function (f) { return supported.indexOf(f) >= 0; });
      if (!formats.length) return zxingReader();
      var detector = new window.BarcodeDetector({formats: formats});
      return function (source) {
        return detector.detect(source).then(function (found) { return found.length ? found[0].rawValue : null; },
                                            function () { return null; });
      };
    }).then(function (r) { read = r; return r; });
  }

  function send(code) {
    stop();
    box.value = code;
    say("Read " + code + ".");
    if (button.form.requestSubmit) button.form.requestSubmit(); else button.form.submit();
  }

  function stop() {
    button.textContent = "Scan with camera";
    running = false;
    last = null;
    if (stream) stream.getTracks().forEach(function (t) { t.stop(); });
    stream = null;
    video.srcObject = null;
    video.hidden = true;
  }

  // a frame at a time, each read before the next is taken; a barcode counts once read twice in a row
  function look() {
    if (!running) return;
    read(video).then(function (code) {
      if (!running) return;
      if (code && rightCheckDigit(code)) {
        if (code === last) return send(code);
        last = code;
      } else {
        last = null;
      }
      setTimeout(look, 100);
    });
  }

  function offerPhoto(why) {
    stop();
    say(why + " Take a photo of the barcode instead.");
    photo.hidden = false;
  }

  function start() {
    panel.hidden = false;
    photo.hidden = true;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      reader();                               // load it while the photo is taken
      return offerPhoto(window.isSecureContext === false
        ? "The browser opens the camera only for a page opened with https:// (docs/pages.md, \"HTTPS\")."
        : "This browser cannot open the camera from a page.");
    }
    say("Starting the camera...");
    button.textContent = "Stop camera";
    Promise.all([reader(), navigator.mediaDevices.getUserMedia({audio: false, video: {
      facingMode: {ideal: "environment"}, width: {ideal: 1280}, height: {ideal: 720}}})]).then(function (got) {
      stream = got[1];
      video.srcObject = stream;
      video.hidden = false;
      return video.play();
    }).then(function () {
      running = true;
      say("Hold the barcode flat in the middle of the picture, close enough to fill about half of it.");
      look();
    }).catch(function (e) {
      var name = e && e.name;
      offerPhoto(name === "NotAllowedError" ? "The camera was not allowed for this page."
                 : name === "NotFoundError" || name === "OverconstrainedError" ? "No camera was found."
                 : "The camera could not start (" + (e && e.message || e) + ").");
    });
  }

  photoInput.addEventListener("change", function () {
    var file = photoInput.files && photoInput.files[0];
    if (!file) return;
    say("Reading the photo...");
    var image = new Image(), url = URL.createObjectURL(file);
    image.onload = function () {
      reader().then(function (r) { return r(image); }).then(function (code) {
        URL.revokeObjectURL(url);
        if (code && rightCheckDigit(code)) send(code);
        else say("No barcode was found in the photo. Try again closer, with the barcode flat, lit and in focus.");
      }, function (e) { say(String(e && e.message || e)); });
    };
    image.onerror = function () { say("The photo could not be opened."); };
    image.src = url;
    photoInput.value = "";
  });

  button.addEventListener("click", function () { if (running || stream) stop(); else start(); });
  panel.querySelector(".camera-stop").addEventListener("click", function () { stop(); panel.hidden = true; });
  window.addEventListener("pagehide", stop);
  document.addEventListener("visibilitychange", function () { if (document.hidden) stop(); });
  button.hidden = false;
})();
