/**
 * Unlock Web Audio on iPhone Safari and Android Chrome.
 *
 * The player creates AudioContext during load, then starts buffers from a
 * promise callback. Mobile browsers keep that context suspended unless
 * resume() runs inside the tap itself, and iOS also needs an HTML audio
 * element played from that same tap (silent switch / audio session).
 * BufferSource.start() is deferred until the context is actually running,
 * because iOS drops sources that were started while suspended.
 *
 * The pedal only listens for mouse events. A finger hold is translated
 * into mousedown/mouseup so the drive sound follows the pedal.
 */
(function () {
  var NativeContext = window.AudioContext || window.webkitAudioContext;
  if (!NativeContext) return;

  var contexts = [];
  var htmlAudio = null;
  var htmlUnlocked = false;

  // Short valid WAV (silence). Played once from the tap to open the iOS audio session.
  var SILENT_WAV =
    "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA=";

  function wrapDecode(ctx) {
    var nativeDecode = ctx.decodeAudioData.bind(ctx);
    ctx.decodeAudioData = function (audioData) {
      var copy = audioData;
      try {
        if (audioData && typeof audioData.slice === "function") {
          copy = audioData.slice(0);
        }
      } catch (err) {
        copy = audioData;
      }
      return new Promise(function (resolve, reject) {
        var settled = false;
        function ok(buffer) {
          if (settled) return;
          settled = true;
          resolve(buffer);
        }
        function bad(err) {
          if (settled) return;
          settled = true;
          reject(err || new Error("decodeAudioData failed"));
        }
        var result;
        try {
          // Callback form still matters on older iOS, which ignores the promise.
          result = nativeDecode(copy, ok, bad);
        } catch (err) {
          bad(err);
          return;
        }
        if (result && typeof result.then === "function") {
          result.then(ok, bad);
        }
      });
    };
  }

  function PatchedAudioContext() {
    var ctx = new NativeContext();
    contexts.push(ctx);
    wrapDecode(ctx);
    try {
      patchBufferSourceStart(ctx);
    } catch (err) {}
    return ctx;
  }
  PatchedAudioContext.prototype = NativeContext.prototype;
  window.AudioContext = PatchedAudioContext;
  if (window.webkitAudioContext) window.webkitAudioContext = PatchedAudioContext;

  function resumeAll() {
    for (var i = 0; i < contexts.length; i++) {
      var ctx = contexts[i];
      if (ctx && ctx.state !== "running" && typeof ctx.resume === "function") {
        try {
          var pending = ctx.resume();
          if (pending && typeof pending.catch === "function") pending.catch(function () {});
        } catch (err) {}
      }
    }
  }

  function playHtmlUnlock() {
    if (htmlUnlocked) return;
    if (!htmlAudio) {
      htmlAudio = document.createElement("audio");
      htmlAudio.setAttribute("playsinline", "true");
      htmlAudio.setAttribute("webkit-playsinline", "true");
      htmlAudio.setAttribute("preload", "auto");
      htmlAudio.src = SILENT_WAV;
      document.body.appendChild(htmlAudio);
    }
    var played;
    try {
      played = htmlAudio.play();
    } catch (err) {
      return;
    }
    if (played && typeof played.then === "function") {
      played.then(
        function () {
          htmlUnlocked = true;
        },
        function () {}
      );
    } else {
      htmlUnlocked = true;
    }
  }

  // Must run synchronously inside the tap, before the player's promise starts buffers.
  function unlockFromGesture() {
    resumeAll();
    playHtmlUnlock();
  }

  ["touchend", "pointerup", "click"].forEach(function (type) {
    window.addEventListener(type, unlockFromGesture, true);
  });

  function patchBufferSourceStart(ctx) {
    var sample = ctx.createBufferSource();
    var sourceProto = Object.getPrototypeOf(sample);
    if (!sourceProto || sourceProto.__zeStartPatched || typeof sourceProto.start !== "function") {
      return;
    }
    var nativeStart = sourceProto.start;
    sourceProto.start = function () {
      var node = this;
      var args = arguments;
      var nodeCtx = node.context;
      if (!nodeCtx || nodeCtx.state === "running") {
        return nativeStart.apply(node, args);
      }
      var pending = null;
      try {
        pending = nodeCtx.resume();
      } catch (err) {}
      var started = false;
      function go() {
        if (started || nodeCtx.state !== "running") return;
        started = true;
        nodeCtx.removeEventListener("statechange", go);
        try {
          nativeStart.apply(node, args);
        } catch (err) {}
      }
      nodeCtx.addEventListener("statechange", go);
      if (pending && typeof pending.then === "function") pending.then(go, go);
      else go();
    };
    sourceProto.__zeStartPatched = true;
  }

  var heldPedal = null;

  function pedalRoot(target) {
    if (!target || !target.closest) return null;
    var svg = target.closest("svg.pedal");
    return svg ? svg.parentNode : null;
  }

  function dispatchMouse(node, type) {
    if (!node) return;
    node.dispatchEvent(
      new MouseEvent(type, { bubbles: true, cancelable: true, view: window })
    );
  }

  document.addEventListener(
    "touchstart",
    function (event) {
      var root = pedalRoot(event.target);
      if (!root) return;
      heldPedal = root;
      event.preventDefault();
      dispatchMouse(root, "mousedown");
    },
    { capture: true, passive: false }
  );

  document.addEventListener(
    "touchend",
    function (event) {
      if (!heldPedal) return;
      event.preventDefault();
      dispatchMouse(heldPedal, "mouseup");
      heldPedal = null;
    },
    { capture: true, passive: false }
  );

  document.addEventListener(
    "touchcancel",
    function () {
      if (!heldPedal) return;
      dispatchMouse(heldPedal, "mouseup");
      heldPedal = null;
    },
    true
  );

  // React writes rotate(0.89 * km/h deg) on .center-origin. The drawn km/h
  // labels sit on the inner ring; highlight the nearest one. Do not add digits.
  var SPEED_DEG_PER_KMH = 0.89;
  var KM_H_LABELS = [
    { angle: -117, kmh: 0 },
    { angle: -89, kmh: 20 },
    { angle: -53, kmh: 60 },
    { angle: -17, kmh: 100 },
    { angle: 18, kmh: 140 },
    { angle: 53, kmh: 180 },
    { angle: 89, kmh: 220 },
    { angle: 107, kmh: 240 }
  ];

  function tagKmHDigits(svg) {
    if (svg.getAttribute("data-kmh-tagged")) return;
    var box = svg.getBoundingClientRect();
    var cx = box.left + box.width * (187.671 / 374);
    var cy = box.top + box.height * (186.084 / 374);
    var groups = svg.querySelectorAll("g");
    for (var i = 0; i < groups.length; i++) {
      var b = groups[i].getBoundingClientRect();
      if (b.width < 8 || b.width > 80 || b.height < 8 || b.height > 40) continue;
      var x = b.left + b.width / 2;
      var y = b.top + b.height / 2;
      var r = Math.hypot(x - cx, y - cy);
      if (r < 110 || r > 140) continue;
      var ang = Math.atan2(x - cx, cy - y) * 180 / Math.PI;
      var best = KM_H_LABELS[0];
      var bestDist = 999;
      for (var k = 0; k < KM_H_LABELS.length; k++) {
        var d = Math.abs(ang - KM_H_LABELS[k].angle);
        if (d < bestDist) {
          bestDist = d;
          best = KM_H_LABELS[k];
        }
      }
      if (bestDist > 16) continue;
      groups[i].setAttribute("data-kmh", String(best.kmh));
      groups[i].classList.add("speed-digit");
    }
    svg.setAttribute("data-kmh-tagged", "1");
  }

  function placeSpeed() {
    var hubs = document.querySelectorAll(".center-origin");
    for (var i = 0; i < hubs.length; i++) {
      var hub = hubs[i];
      var pointer = hub.querySelector(".pointer");
      if (pointer) pointer.style.setProperty("display", "none", "important");
      var raw = hub.style.transform || "";
      var match = /rotate\(([-+\d.eE]+)deg\)/.exec(raw);
      var speedDeg = match ? parseFloat(match[1]) : 0;
      if (!isFinite(speedDeg) || raw.indexOf("translate(") !== -1) {
        var saved = hub.getAttribute("data-speed-rotate");
        match = saved ? /rotate\(([-+\d.eE]+)deg\)/.exec(saved) : null;
        speedDeg = match ? parseFloat(match[1]) : 0;
      } else {
        hub.setAttribute("data-speed-rotate", raw);
      }
      if (!isFinite(speedDeg)) speedDeg = 0;
      var kmh = Math.max(0, speedDeg / SPEED_DEG_PER_KMH);
      var svg = hub.ownerSVGElement;
      if (!svg) continue;
      tagKmHDigits(svg);
      var labels = svg.querySelectorAll(".speed-digit");
      var nearest = null;
      var nearestDelta = 1e9;
      for (var n = 0; n < labels.length; n++) {
        var value = parseFloat(labels[n].getAttribute("data-kmh"));
        var delta = Math.abs(value - kmh);
        if (delta < nearestDelta) {
          nearestDelta = delta;
          nearest = labels[n];
        }
      }
      for (var h = 0; h < labels.length; h++) {
        labels[h].classList.toggle("speed-digit--hot", labels[h] === nearest);
      }
    }
    requestAnimationFrame(placeSpeed);
  }

  requestAnimationFrame(placeSpeed);
})();
