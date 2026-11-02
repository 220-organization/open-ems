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

  // Rest pose puts the tip on the 0 tick, inside the ring. Added to the speed
  // angle React writes on .center-origin (positive degrees climb the left side).
  var NEEDLE_ZERO_DEG = -40.6;

  function placeNeedles() {
    var hubs = document.querySelectorAll(".center-origin");
    for (var i = 0; i < hubs.length; i++) {
      var hub = hubs[i];
      var pointer = hub.querySelector(".pointer");
      if (!pointer) continue;
      var match = /rotate\(([-+\d.eE]+)deg\)/.exec(hub.style.transform || "");
      var speedDeg = match ? parseFloat(match[1]) : 0;
      if (!isFinite(speedDeg)) speedDeg = 0;
      pointer.style.setProperty("transform-origin", "246.4px 178px", "important");
      pointer.style.setProperty(
        "transform",
        "rotate(" + (NEEDLE_ZERO_DEG + speedDeg).toFixed(3) + "deg) scale(0.78)",
        "important"
      );
    }
    requestAnimationFrame(placeNeedles);
  }

  requestAnimationFrame(placeNeedles);
})();
